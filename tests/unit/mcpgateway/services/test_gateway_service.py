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
from datetime import datetime, timezone, timedelta
import sys
from types import SimpleNamespace
from typing import TypeVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest
from pydantic import ValidationError
from url_normalize import url_normalize

# First-Party
# ---------------------------------------------------------------------------
# Application imports
# ---------------------------------------------------------------------------
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.schemas import GatewayCreate, GatewayUpdate
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayError,
    GatewayNameConflictError,
    GatewayNotFoundError,
    GatewayService,
    GatewayDuplicateConflictError,
    OAuthToolValidationError,
)

# ---------------------------------------------------------------------------
# Helpers & global monkey-patches
# ---------------------------------------------------------------------------


_R = TypeVar("_R")


def _make_execute_result(*, scalar: _R | None = None, scalars_list: list[_R] | None = None, rowcount: int = 0) -> MagicMock:
    """
    Return a MagicMock that behaves like the SQLAlchemy Result object the
    service expects after ``Session.execute``:

        - .scalar_one_or_none()  -> *scalar*
        - .scalars().all()      -> *scalars_list*  (defaults to [])
        - .rowcount             -> *rowcount* (for UPDATE/DELETE statements)

    This lets us emulate both the "fetch one" path and the "fetch many"
    path with a single helper.
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    result.rowcount = rowcount
    return result


def _make_gateway(**overrides):
    base = {
        "name": "test-gateway",
        "url": "http://example.com",
        "description": "Test gateway",
        "transport": "sse",
        "tags": [],
        "passthrough_headers": None,
        "auth_type": None,
        "auth_value": None,
        "auth_headers": None,
        "auth_query_param_key": None,
        "auth_query_param_value": None,
        "auth_query_params": None,
        "oauth_config": None,
        "one_time_auth": False,
        "ca_certificate": None,
        "ca_certificate_sig": None,
        "signing_algorithm": None,
        "visibility": "public",
        "enabled": True,
        "team_id": None,
        "tools": [],
        "resources": [],
        "prompts": [],
        "capabilities": {},
        "version": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    # Clear SSL context cache before each test for isolation
    from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache
    clear_ssl_context_cache()

    with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, \
         patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


class _PassthroughMasked:
    """Wrapper that delegates attribute access and provides .masked()."""

    def __init__(self, obj):
        self._obj = obj

    def masked(self):
        return self._obj

    def model_dump(self, **kw):
        if hasattr(self._obj, "model_dump"):
            return self._obj.model_dump(**kw)
        return vars(self._obj)

    def __getattr__(self, name):
        return getattr(self._obj, name)


@pytest.fixture(autouse=True)
def _bypass_gatewayread_validation(monkeypatch):
    """
    The real GatewayService returns ``GatewayRead.model_validate(db_obj).masked()``.
    The DB objects we feed in here are MagicMocks, not real models, and
    Pydantic hates that.  We therefore stub out `GatewayRead.model_validate`
    so it returns a thin wrapper that supports ``.masked()``.
    """
    # First-Party
    from mcpgateway.schemas import GatewayRead

    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: _PassthroughMasked(x)))


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

    # Mock email_team relationship and team property
    # Use instance-level assignment (MagicMock allows this)
    mock_email_team = MagicMock()
    mock_email_team.name = "Test Team"
    gw.email_team = mock_email_team
    gw.team = "Test Team"  # Instance-level mock for the team property
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
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # name-conflict check
                _make_execute_result(scalars_list=[]),  # tool lookup
            ]
        )
        test_db.add = Mock()
        test_db.flush = Mock()  # Implementation uses flush() not commit()
        test_db.refresh = Mock()
        # Mock query for _check_gateway_uniqueness
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

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
        test_db.flush.assert_called_once()  # Implementation uses flush() not commit()
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
        test_db.flush = Mock()  # Implementation uses flush() not commit()
        test_db.refresh = Mock()
        # Mock query for _check_gateway_uniqueness
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

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
        test_db.flush.assert_called_once()  # Implementation uses flush() not commit()
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
        test_db.flush = Mock(side_effect=Exception("Database error"))  # Implementation uses flush() not commit()
        test_db.rollback = Mock()
        # Mock query for _check_gateway_uniqueness
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

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
        test_db.rollback = Mock()

        gateway_service._initialize_gateway = AsyncMock(side_effect=ValueError("Invalid gateway configuration"))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(ValueError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Invalid gateway configuration" in str(exc_info.value)
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_gateway_runtime_error(self, gateway_service, test_db):
        """Test RuntimeError during gateway registration."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.rollback = Mock()

        gateway_service._initialize_gateway = AsyncMock(side_effect=RuntimeError("Runtime error occurred"))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(RuntimeError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Runtime error occurred" in str(exc_info.value)
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_gateway_integrity_error(self, gateway_service, test_db):
        """Test IntegrityError during gateway registration."""
        # Third-Party
        from sqlalchemy.exc import IntegrityError as SQLIntegrityError

        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add = Mock()
        test_db.rollback = Mock()
        test_db.flush = Mock(side_effect=SQLIntegrityError("statement", "params", BaseException("orig")))  # Implementation uses flush()
        # Mock query for _check_gateway_uniqueness
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(SQLIntegrityError):
            await gateway_service.register_gateway(test_db, gateway_create)

        test_db.rollback.assert_called_once()

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
        test_db.flush = Mock()  # Implementation uses flush() not commit()
        test_db.refresh = Mock()
        # Mock query for _check_gateway_uniqueness
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

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
        test_db.flush.assert_called_once()  # Implementation uses flush() not commit()
        gateway_service._initialize_gateway.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_gateway_exception_rollback(self, gateway_service, test_db):
        """Test rollback on exception during gateway registration."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add = Mock()
        test_db.flush = Mock(side_effect=Exception("Flush failed"))  # Implementation uses flush() not commit()
        test_db.rollback = Mock()
        # Mock query for _check_gateway_uniqueness
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(Exception) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Flush failed" in str(exc_info.value)  # Error message matches the mocked exception
        test_db.rollback.assert_called_once()  # Exception handlers now rollback to prevent orphaned records

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

        # Assert that execute was called once (query with eager load)
        assert test_db.execute.call_count == 1
        # Optionally, print or check call arguments for debugging
        # print(test_db.execute.call_args_list)
        assert len(result) == 1
        assert result[0].name == "test_gateway"

    @pytest.mark.asyncio
    async def test_list_gateways_cache_hit(self, gateway_service, test_db, monkeypatch):
        """Cache hit should return cached gateways without DB query.

        SECURITY: Caching only applies to public-only tokens (token_teams=[]).
        Admin bypass (token_teams=None) and team-scoped tokens never use cache.
        """
        cache = SimpleNamespace(
            hash_filters=MagicMock(return_value="hash"),
            get=AsyncMock(return_value={"gateways": [{"name": "cached"}], "next_cursor": "next"}),
            set=AsyncMock(),
        )

        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: cache)

        # Mock must return object with masked() method since cache reads now apply masking
        class MockGatewayRead:
            def __init__(self, data):
                self.name = data["name"]
                self._masked_called = False

            def masked(self):
                self._masked_called = True
                return self

        monkeypatch.setattr("mcpgateway.services.gateway_service.GatewayRead.model_validate", lambda data: MockGatewayRead(data))

        test_db.execute = Mock()
        # SECURITY: Must use token_teams=[] (public-only) to enable caching
        result, next_cursor = await gateway_service.list_gateways(test_db, token_teams=[])

        assert next_cursor == "next"
        assert len(result) == 1
        assert result[0].name == "cached"
        # SECURITY: Verify .masked() is called on cache reads to prevent credential leakage
        assert result[0]._masked_called, "Cache reads must call .masked() to prevent credential leakage"
        test_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_gateways_team_filter_no_access(self, gateway_service, test_db, monkeypatch):
        """Team filter should return empty when user lacks access."""
        class DummyTeamService:
            def __init__(self, _db):
                self.db = _db

            async def get_user_teams(self, _email):
                return [SimpleNamespace(id="team-1")]

        monkeypatch.setattr("mcpgateway.services.base_service.TeamManagementService", DummyTeamService)

        test_db.execute = Mock(return_value=_make_execute_result(scalars_list=[]))
        result, next_cursor = await gateway_service.list_gateways(test_db, user_email="user@example.com", team_id="team-2")

        assert result == []
        assert next_cursor is None
        # Query IS executed but returns empty due to WHERE FALSE condition
        test_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_gateway(self, gateway_service, mock_gateway, test_db):
        """Gateway is fetched and returned by ID."""
        mock_gateway.masked = Mock(return_value=mock_gateway)
        mock_gateway.team_id = 1  # Ensure team_id is a real value
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        result = await gateway_service.get_gateway(test_db, 1)
        test_db.execute.assert_called_once()
        assert result.name == "test_gateway"
        assert result.capabilities == mock_gateway.capabilities

    @pytest.mark.asyncio
    async def test_get_gateway_not_found(self, gateway_service, test_db):
        """Missing ID → GatewayNotFoundError."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        with pytest.raises(GatewayNotFoundError):
            await gateway_service.get_gateway(test_db, 999)

    @pytest.mark.asyncio
    async def test_get_gateway_inactive(self, gateway_service, mock_gateway, test_db):
        """Inactive gateway is not returned unless explicitly asked for."""
        mock_gateway.enabled = False
        mock_gateway.id = 1
        mock_gateway.team_id = 1  # Ensure team_id is a real value
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))

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
            test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
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
    # SET STATE ACTIVE / INACTIVE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_set_gateway_state(self, gateway_service, mock_gateway, test_db):
        """Deactivating an active gateway triggers bulk state updates + event."""
        # First call returns gateway (SELECT), subsequent calls return UPDATE results
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=mock_gateway),  # get_for_update SELECT
                _make_execute_result(rowcount=1),  # UPDATE tools
                _make_execute_result(rowcount=1),  # UPDATE prompts
                _make_execute_result(rowcount=1),  # UPDATE resources
            ]
        )
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Setup gateway service mocks
        gateway_service._notify_gateway_activated = AsyncMock()
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, [], [], []))

        # Patch model_validate to return a mock with .masked()
        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            result = await gateway_service.set_gateway_state(test_db, 1, activate=False)

        assert mock_gateway.enabled is False
        gateway_service._notify_gateway_deactivated.assert_called_once()
        # Bulk UPDATE is used instead of individual set_*_state calls
        assert test_db.execute.call_count >= 2  # At least SELECT + UPDATE tools
        assert result == mock_gateway_read

    @pytest.mark.asyncio
    async def test_set_gateway_state_activate(self, gateway_service, mock_gateway, test_db):
        """Test activating an inactive gateway."""
        mock_gateway.enabled = False
        # Initialize collections as empty lists to avoid SQLAlchemy mapping errors
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []
        # First call returns gateway (SELECT), subsequent calls return UPDATE results
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=mock_gateway),  # get_for_update SELECT
                _make_execute_result(rowcount=1),  # UPDATE tools
                _make_execute_result(rowcount=1),  # UPDATE prompts
                _make_execute_result(rowcount=1),  # UPDATE resources
            ]
        )
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Setup gateway service mocks
        gateway_service._notify_gateway_activated = AsyncMock()
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, [], [], []))

        # Patch model_validate to return a mock with .masked()
        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            result = await gateway_service.set_gateway_state(test_db, 1, activate=True)

        assert mock_gateway.enabled is True
        gateway_service._notify_gateway_activated.assert_called_once()
        # Bulk UPDATE is used instead of individual set_*_state calls
        assert test_db.execute.call_count >= 2  # At least SELECT + UPDATE tools
        assert result == mock_gateway_read

    @pytest.mark.asyncio
    async def test_set_gateway_state_only_update_reachable_skips_prompts_resources(self, gateway_service, mock_gateway, test_db):
        """Test that only_update_reachable=True skips prompt/resource state updates."""
        # First call returns gateway (SELECT), second call returns UPDATE result for tools only
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=mock_gateway),  # get_for_update SELECT
                _make_execute_result(rowcount=1),  # UPDATE tools (reachable only)
            ]
        )
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Setup gateway service mocks
        gateway_service._notify_gateway_offline = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, [], [], []))

        # Patch model_validate to return a mock with .masked()
        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            result = await gateway_service.set_gateway_state(test_db, 1, activate=True, reachable=False, only_update_reachable=True)

        # With bulk UPDATE, we have SELECT + UPDATE tools only (no prompts/resources)
        assert test_db.execute.call_count == 2  # SELECT + UPDATE tools
        assert result == mock_gateway_read

    @pytest.mark.asyncio
    async def test_set_gateway_state_not_found(self, gateway_service, test_db):
        """Test setting state of non-existent gateway."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.set_gateway_state(test_db, 999, activate=True)

        assert "Gateway not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_set_gateway_state_with_tools_error(self, gateway_service, mock_gateway, test_db):
        """Test setting gateway state when bulk tool UPDATE fails."""
        # First call returns gateway, second call (bulk UPDATE) fails
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=mock_gateway),  # get_for_update SELECT
                Exception("Bulk tool update failed"),  # UPDATE tools fails
            ]
        )
        test_db.commit = Mock()
        test_db.refresh = Mock()
        test_db.rollback = Mock()

        # Setup gateway service mocks
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, [], [], []))

        # The set_gateway_state method will catch the exception and raise GatewayError
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.set_gateway_state(test_db, 1, activate=False)

        assert "Failed to set gateway state" in str(exc_info.value)
        assert "Bulk tool update failed" in str(exc_info.value)
        test_db.rollback.assert_called_once()

    # ────────────────────────────────────────────────────────────────────
    # DELETE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_gateway(self, gateway_service, mock_gateway, test_db):
        """Gateway is removed and subscribers are notified."""
        # Mock the fetchone result for DELETE ... RETURNING
        mock_fetch_result = Mock()
        mock_fetch_result.fetchone.return_value = (mock_gateway.id,)

        # First execute call returns gateway (selectinload query), rest are for bulk deletes, last is DELETE RETURNING
        execute_mock = Mock(
            side_effect=[
                _make_execute_result(scalar=mock_gateway),  # Initial select
                Mock(),  # Tool metrics delete
                Mock(),  # Tool association delete
                Mock(),  # Tool delete
                Mock(),  # Resource metrics delete
                Mock(),  # Resource association delete
                Mock(),  # Resource subscription delete
                Mock(),  # Resource delete
                Mock(),  # Prompt metrics delete
                Mock(),  # Prompt association delete
                Mock(),  # Prompt delete
                mock_fetch_result,  # DELETE ... RETURNING
            ]
        )
        test_db.execute = execute_mock
        test_db.commit = Mock()
        test_db.expire = Mock()  # For expiring gateway after bulk deletes

        gateway_service._notify_gateway_deleted = AsyncMock()

        await gateway_service.delete_gateway(test_db, 1)

        gateway_service._notify_gateway_deleted.assert_called_once()
        # Verify execute was called multiple times (select + bulk deletes + final delete)
        assert test_db.execute.call_count >= 2

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
    async def test_initialize_gateway_oauth_auth_code_returns_empty(self, gateway_service):
        """OAuth auth_code should short-circuit and skip connection unless flag set."""
        gateway_service.connect_to_sse_server = AsyncMock(return_value=({"tools": {}}, [], [], []))

        oauth_config = {"grant_type": "authorization_code"}
        capabilities, tools, resources, prompts = await gateway_service._initialize_gateway(
            "http://test.example.com",
            authentication=None,
            transport="SSE",
            auth_type="oauth",
            oauth_config=oauth_config,
            oauth_auto_fetch_tool_flag=False,
        )

        assert capabilities == {}
        assert tools == []
        assert resources == []
        assert prompts == []
        gateway_service.connect_to_sse_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_gateway_oauth_client_credentials(self, gateway_service):
        """OAuth client_credentials should fetch token and connect."""
        gateway_service.connect_to_sse_server = AsyncMock(return_value=({"tools": {}}, [], [], []))
        gateway_service.oauth_manager.get_access_token = AsyncMock(return_value="token123")

        oauth_config = {"grant_type": "client_credentials"}
        await gateway_service._initialize_gateway(
            "http://test.example.com",
            authentication=None,
            transport="SSE",
            auth_type="oauth",
            oauth_config=oauth_config,
        )

        gateway_service.oauth_manager.get_access_token.assert_awaited_once_with(oauth_config)
        _, auth_headers, *_ = gateway_service.connect_to_sse_server.call_args.args
        assert auth_headers == {"Authorization": "Bearer token123"}

    @pytest.mark.asyncio
    async def test_initialize_gateway_oauth_client_credentials_error(self, gateway_service):
        """OAuth token fetch errors should raise GatewayConnectionError."""
        gateway_service.oauth_manager.get_access_token = AsyncMock(side_effect=Exception("oauth fail"))

        oauth_config = {"grant_type": "client_credentials"}
        with pytest.raises(GatewayConnectionError):
            await gateway_service._initialize_gateway(
                "http://test.example.com",
                authentication=None,
                transport="SSE",
                auth_type="oauth",
                oauth_config=oauth_config,
            )

    @pytest.mark.asyncio
    async def test_list_gateway_with_tags(self, gateway_service, mock_gateway):
        """Test listing gateways with tag filtering."""
        # Third-Party

        # Mock query chain - needs to support chaining through order_by, where, limit
        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.options.return_value = mock_query

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
            with patch("mcpgateway.services.gateway_service.json_contains_tag_expr") as mock_json_contains:
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
                assert result == [mocked_gateway_read]
    @pytest.mark.asyncio
    async def test_register_gateway_with_cache_mode(self, gateway_service):
        """Test registering a gateway with explicit cache mode (default behavior)."""
        gateway_data = GatewayCreate(
            name="Cache Mode Gateway",
            url="https://cache-gateway.example.com",
            description="Gateway with cache mode",
            transport="SSE",
            auth_type="bearer",
            auth_token="test-token",
            gateway_mode="cache",  # Explicit cache mode
        )

        session = MagicMock()
        session.execute.return_value = _make_execute_result(scalar=None)
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()

        # Mock _initialize_gateway to return empty lists
        async def mock_init(*args, **kwargs):
            return {}, [], [], []

        gateway_service._initialize_gateway = mock_init

        await gateway_service.register_gateway(
            session,
            gateway_data,
            created_by="test@example.com",
        )

        # Verify gateway_mode was set to cache
        add_call_args = session.add.call_args[0][0]
        assert hasattr(add_call_args, "gateway_mode")
        assert add_call_args.gateway_mode == "cache"

    @pytest.mark.asyncio
    async def test_register_gateway_with_direct_proxy_mode(self, gateway_service):
        """Test registering a gateway with direct_proxy mode."""
        gateway_data = GatewayCreate(
            name="Direct Proxy Gateway",
            url="https://proxy-gateway.example.com",
            description="Gateway with direct proxy mode",
            transport="STREAMABLEHTTP",
            auth_type="bearer",
            auth_token="test-token",
            gateway_mode="direct_proxy",  # Direct proxy mode
        )

        session = MagicMock()
        session.execute.return_value = _make_execute_result(scalar=None)
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()

        # Mock _initialize_gateway to return empty lists
        async def mock_init(*args, **kwargs):
            return {}, [], [], []

        gateway_service._initialize_gateway = mock_init

        # Enable direct_proxy feature flag
        mock_settings = MagicMock()
        mock_settings.mcpgateway_direct_proxy_enabled = True
        with patch("mcpgateway.services.gateway_service.settings", mock_settings):
            await gateway_service.register_gateway(
                session,
                gateway_data,
                created_by="test@example.com",
            )

        # Verify gateway_mode was set to direct_proxy
        add_call_args = session.add.call_args[0][0]
        assert hasattr(add_call_args, "gateway_mode")
        assert add_call_args.gateway_mode == "direct_proxy"

    @pytest.mark.asyncio
    async def test_register_gateway_default_mode_is_cache(self, gateway_service):
        """Test that gateway_mode defaults to 'cache' when not specified."""
        gateway_data = GatewayCreate(
            name="Default Mode Gateway",
            url="https://default-gateway.example.com",
            description="Gateway without explicit mode",
            transport="SSE",
            auth_type="bearer",
            auth_token="test-token",
            # gateway_mode not specified - should default to "cache"
        )

        session = MagicMock()
        session.execute.return_value = _make_execute_result(scalar=None)
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()

        # Mock _initialize_gateway to return empty lists
        async def mock_init(*args, **kwargs):
            return {}, [], [], []

        gateway_service._initialize_gateway = mock_init

        await gateway_service.register_gateway(
            session,
            gateway_data,
            created_by="test@example.com",
        )

        # Verify gateway_mode defaults to cache
        add_call_args = session.add.call_args[0][0]
        assert hasattr(add_call_args, "gateway_mode")
        assert add_call_args.gateway_mode == "cache"

    @pytest.mark.asyncio
    async def test_update_gateway_mode_from_cache_to_direct_proxy(self, gateway_service):
        """Test updating gateway mode from cache to direct_proxy."""
        # Existing gateway with cache mode
        existing_gateway = _make_gateway(
            id="gw-update-123",
            name="Update Test Gateway",
            url="https://update-gateway.example.com",
            gateway_mode="cache",
        )

        session = MagicMock()
        session.execute.return_value = _make_execute_result(scalar=existing_gateway)
        session.commit = MagicMock()
        session.refresh = MagicMock()

        # Update to direct_proxy mode
        update_data = GatewayUpdate(gateway_mode="direct_proxy")

        # Enable direct_proxy feature flag
        mock_settings = MagicMock()
        mock_settings.mcpgateway_direct_proxy_enabled = True
        with patch("mcpgateway.services.gateway_service.settings", mock_settings):
            await gateway_service.update_gateway(
                session,
                "gw-update-123",
                update_data,
                modified_by="admin@example.com",
            )

        # Verify gateway_mode was updated
        assert existing_gateway.gateway_mode == "direct_proxy"
        session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_gateway_mode_from_direct_proxy_to_cache(self, gateway_service):
        """Test updating gateway mode from direct_proxy to cache."""
        # Existing gateway with direct_proxy mode
        existing_gateway = _make_gateway(
            id="gw-update-456",
            name="Proxy to Cache Gateway",
            url="https://proxy-to-cache.example.com",
            gateway_mode="direct_proxy",
        )

        session = MagicMock()
        session.execute.return_value = _make_execute_result(scalar=existing_gateway)
        session.commit = MagicMock()
        session.refresh = MagicMock()

        # Update to cache mode
        update_data = GatewayUpdate(gateway_mode="cache")

        await gateway_service.update_gateway(
            session,
            "gw-update-456",
            update_data,
            modified_by="admin@example.com",
        )

        # Verify gateway_mode was updated
        assert existing_gateway.gateway_mode == "cache"
        session.commit.assert_called()



class TestGatewayRefresh:
    """Test suite for gateway refresh logic (internal and manual)."""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session context manager."""
        session = MagicMock()
        session.commit = MagicMock()
        session.flush = MagicMock()
        session.execute.return_value = _make_execute_result(scalar=None)

        # Mock dirty objects set
        session.dirty = set()

        # Mock context manager
        ctx = MagicMock()
        ctx.__enter__.return_value = session
        ctx.__exit__.return_value = None
        return ctx

    @pytest.fixture
    def mock_gateway_with_relations(self):
        """Mock gateway with tools, resources, prompts relations."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw-123"
        gw.name = "test_gateway"
        gw.url = "http://example.com"
        gw.enabled = True
        gw.reachable = True
        gw.tools = []
        gw.resources = []
        gw.prompts = []
        return gw

    @pytest.mark.asyncio
    async def test_refresh_gateway_success_all_changed(self, gateway_service, mock_gateway_with_relations, mock_db_session):
        """Test successful refresh where tools, resources, prompts are all updated."""
        # Setup mocks
        session = mock_db_session.__enter__()
        # Mock gateway fetch
        session.execute.return_value = _make_execute_result(scalar=mock_gateway_with_relations)

        # Mock fresh_db_session to return our mock session
        with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
            # Mock _initialize_gateway to return new data
            new_tools = [MagicMock(name="tool1")]
            new_resources = [MagicMock(uri="res1")]
            new_prompts = [MagicMock(name="prompt1")]

            gateway_service._initialize_gateway = AsyncMock(return_value=({}, new_tools, new_resources, new_prompts))  # capabilities

            # Mock update/create helpers
            gateway_service._update_or_create_tools = Mock(return_value=[MagicMock()])
            gateway_service._update_or_create_resources = Mock(return_value=[MagicMock()])
            gateway_service._update_or_create_prompts = Mock(return_value=[MagicMock()])

            # Simulate dirty objects for count calculation
            session.dirty = {MagicMock(spec=DbTool), MagicMock(spec=DbResource), MagicMock(spec=DbPrompt)}  # mock updated objects

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123", gateway=mock_gateway_with_relations)

            assert result["success"] is True
            assert result["tools_added"] == 1
            assert result["resources_added"] == 1
            assert result["prompts_added"] == 1
            # Note: dirty check logic in actual code compares vs snapshot, simplified here

    @pytest.mark.asyncio
    async def test_refresh_gateway_no_changes(self, gateway_service, mock_gateway_with_relations, mock_db_session):
        """Test refresh with no changes detected."""
        # Setup mock session to return gateway when queried
        session = mock_db_session.__enter__()
        session.execute.return_value = _make_execute_result(scalar=mock_gateway_with_relations)

        with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
            # Mock empty return from initialize
            gateway_service._initialize_gateway = AsyncMock(return_value=({}, [], [], []))

            # Mock update methods to avoid real execution errors
            gateway_service._update_or_create_tools = Mock(return_value=[])
            gateway_service._update_or_create_resources = Mock(return_value=[])
            gateway_service._update_or_create_prompts = Mock(return_value=[])

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123", gateway=mock_gateway_with_relations)

            if not result.get("success", True):
                pytest.fail(f"Refresh failed with error: {result.get('error')}")

            assert result["success"] is True
            assert result["tools_added"] == 0
            assert result["resources_added"] == 0
            assert result["prompts_added"] == 0

    @pytest.mark.asyncio
    async def test_refresh_gateway_not_found(self, gateway_service, mock_db_session):
        """Test refresh fails when gateway doesn't exist."""
        session = mock_db_session.__enter__()
        session.execute.return_value = _make_execute_result(scalar=None)

        with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
            result = await gateway_service._refresh_gateway_tools_resources_prompts("non-existent-id")

            # Depending on implementation, it may return empty result or error
            # Code says: logger.warning and return result (which defaults success=True but counts 0)
            assert result["success"] is True  # Based on code reading: returns default result
            assert result["tools_added"] == 0

    @pytest.mark.asyncio
    async def test_refresh_gateway_inactive(self, gateway_service, mock_gateway_with_relations):
        """Test refresh is skipped for inactive gateway."""
        mock_gateway_with_relations.enabled = False

        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123", gateway=mock_gateway_with_relations)

        assert result["tools_added"] == 0
        # Should verify no init calls made
        assert not hasattr(gateway_service._initialize_gateway, "called") or not gateway_service._initialize_gateway.called

    @pytest.mark.asyncio
    async def test_refresh_gateway_connection_error(self, gateway_service, mock_gateway_with_relations):
        """Test handling of connection error during refresh."""
        gateway_service._initialize_gateway = AsyncMock(side_effect=Exception("Connection failed"))

        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123", gateway=mock_gateway_with_relations)

        assert result["success"] is False
        assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_manual_refresh_success(self, gateway_service, mock_gateway_with_relations, mock_db_session):
        """Test successful manual refresh."""
        session = mock_db_session.__enter__()
        session.execute.return_value = _make_execute_result(scalar=mock_gateway_with_relations)

        with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
            # Mock the internal refresh method (which handles last_refresh_at update internally)
            gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
                return_value={"success": True, "tools_added": 5, "tools_removed": 0, "resources_added": 0, "resources_removed": 0, "prompts_added": 0, "prompts_removed": 0}
            )

            result = await gateway_service.refresh_gateway_manually("gw-123")

            assert result["success"] is True
            assert result["tools_added"] == 5
            assert "duration_ms" in result
            assert "refreshed_at" in result
            gateway_service._refresh_gateway_tools_resources_prompts.assert_called_once()
            # Verify internal method was called with correct params
            args, kwargs = gateway_service._refresh_gateway_tools_resources_prompts.call_args
            assert kwargs["created_via"] == "manual_refresh"

    @pytest.mark.asyncio
    async def test_manual_refresh_gateway_not_found(self, gateway_service, mock_db_session):
        """Test manual refresh raises error if gateway not found."""
        session = mock_db_session.__enter__()
        session.execute.return_value = _make_execute_result(scalar=None)

        with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
            with pytest.raises(GatewayNotFoundError):
                await gateway_service.refresh_gateway_manually("non-existent-id")

    @pytest.mark.asyncio
    async def test_manual_refresh_concurrency(self, gateway_service, mock_gateway_with_relations, mock_db_session):
        """Test error when refresh lock is already held."""
        session = mock_db_session.__enter__()
        session.execute.return_value = _make_execute_result(scalar=mock_gateway_with_relations)

        # Manually acquire the lock first
        lock = gateway_service._get_refresh_lock("gw-123")
        await lock.acquire()

        with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
            try:
                with pytest.raises(GatewayError) as exc_info:
                    await gateway_service.refresh_gateway_manually("gw-123")
                assert "Refresh already in progress" in str(exc_info.value)
            finally:
                lock.release()

    @pytest.mark.asyncio
    async def test_manual_refresh_passthrough_headers(self, gateway_service, mock_gateway_with_relations, mock_db_session):
        """Test manual refresh uses passthrough headers."""
        session = mock_db_session.__enter__()
        session.execute.return_value = _make_execute_result(scalar=mock_gateway_with_relations)

        with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
            with patch("mcpgateway.services.gateway_service.get_passthrough_headers") as mock_get_headers:
                mock_get_headers.return_value = {"x-custom": "value"}
                # Return full dict structure expected by logging
                gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
                    return_value={
                        "success": True,
                        "tools_added": 0,
                        "tools_removed": 0,
                        "tools_updated": 0,
                        "resources_added": 0,
                        "resources_removed": 0,
                        "resources_updated": 0,
                        "prompts_added": 0,
                        "prompts_removed": 0,
                        "prompts_updated": 0,
                        "duration_ms": 0,
                    }
                )

                await gateway_service.refresh_gateway_manually("gw-123", request_headers={"x-foo": "bar"})

                mock_get_headers.assert_called_once()
                # Verify headers passed to internal method
                args, kwargs = gateway_service._refresh_gateway_tools_resources_prompts.call_args
                assert kwargs["pre_auth_headers"] == {"x-custom": "value"}

    def test_validate_tools_partial_failure(self, gateway_service):
        """Test tool validation logs errors but returns valid tools and validation errors."""
        tools = [
            {"name": "valid_tool", "description": "valid", "inputSchema": {}},
            {"name": "invalid_tool", "integration_type": "INVALID_TYPE"},  # Invalid integration_type, should fail
        ]

        valid_tools, validation_errors = gateway_service._validate_tools(tools)

        assert len(valid_tools) == 1
        assert valid_tools[0].name == "valid_tool"
        assert len(validation_errors) == 1
        assert "invalid_tool" in validation_errors[0]

    def test_validate_tools_all_invalid(self, gateway_service):
        """Test failure when all tools are invalid."""
        tools = [
            {"name": "invalid1", "integration_type": "INVALID_TYPE"},
            {"name": "invalid2", "integration_type": "INVALID_TYPE"},
        ]

        with pytest.raises(GatewayConnectionError) as exc:
            gateway_service._validate_tools(tools)
        assert "validation" in str(exc.value)

    def test_validate_tools_all_invalid_oauth(self, gateway_service):
        """Test failure when all tools are invalid in oauth context."""
        tools = [{"name": "invalid", "integration_type": "INVALID_TYPE"}]

        with pytest.raises(OAuthToolValidationError) as exc:
            gateway_service._validate_tools(tools, context="oauth")
        assert "OAuth tool fetch failed" in str(exc.value)

    def test_validate_tools_depth_limit(self, gateway_service):
        """Test handling of recursion depth error in validation."""
        # We simulate this by mocking ToolCreate.model_validate to raise ValueError
        with patch("mcpgateway.services.gateway_service.ToolCreate.model_validate") as mock_validate:
            mock_validate.side_effect = ValueError("JSON structure exceeds maximum depth")

            # Should not raise exception, but log error and return empty valid list
            # Since all failed, it will raise GatewayConnectionError eventually
            with pytest.raises(GatewayConnectionError):
                gateway_service._validate_tools([{"name": "deep_tool"}])

    @pytest.mark.asyncio
    async def test_publish_event(self, gateway_service):
        """Test event publishing."""
        # Mock internal event service
        gateway_service._event_service = AsyncMock()
        event = {"type": "test", "data": "foo"}

        await gateway_service._publish_event(event)

        gateway_service._event_service.publish_event.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_connect_to_sse_server_without_validation_success(self, gateway_service):
        """Test successful connection without URL validation."""

        # Mock dependencies
        mock_session = AsyncMock()

        # Mock responses
        mock_init_response = MagicMock()
        mock_init_response.capabilities.model_dump.return_value = {"resources": True, "prompts": True}
        mock_session.initialize.return_value = mock_init_response

        mock_list_tools = MagicMock()
        mock_list_tools.tools = [MagicMock(model_dump=MagicMock(return_value={"name": "tool1", "inputSchema": {}}))]
        mock_session.list_tools.return_value = mock_list_tools

        mock_list_resources = MagicMock()
        mock_list_resources.resources = [MagicMock(model_dump=MagicMock(return_value={"uri": "res1", "name": "res1"}))]
        mock_session.list_resources.return_value = mock_list_resources
        mock_session.list_resource_templates.return_value = MagicMock(resourceTemplates=[])

        mock_list_prompts = MagicMock()
        mock_list_prompts.prompts = [MagicMock(model_dump=MagicMock(return_value={"name": "prompt1"}))]
        mock_session.list_prompts.return_value = mock_list_prompts

        # Context managers
        mock_sse_cm = AsyncMock()
        mock_sse_cm.__aenter__.return_value = (MagicMock(), MagicMock())
        mock_sse_cm.__aexit__.return_value = None

        mock_client_cm = AsyncMock()
        mock_client_cm.__aenter__.return_value = mock_session
        mock_client_cm.__aexit__.return_value = None

        with patch("mcpgateway.services.gateway_service.sse_client", return_value=mock_sse_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=mock_client_cm):
                # Execute
                capabilities, tools, resources, prompts = await gateway_service._connect_to_sse_server_without_validation("http://test.com")

                assert len(tools) == 1
                assert len(resources) == 1
                assert len(prompts) == 1
                assert capabilities["resources"] is True

    @pytest.mark.asyncio
    async def test_connect_to_sse_server_without_validation_fetch_errors(self, gateway_service):
        """Test resilience when resource/prompt fetch fails."""

        # Mock dependencies
        mock_session = AsyncMock()
        # Mock responses
        mock_init_response = MagicMock()
        mock_init_response.capabilities.model_dump.return_value = {"resources": True, "prompts": True}
        mock_session.initialize.return_value = mock_init_response

        mock_list_tools = MagicMock()
        mock_list_tools.tools = []
        mock_session.list_tools.return_value = mock_list_tools

        # Simulate failures
        mock_session.list_resources.side_effect = Exception("Resource fetch failed")
        mock_session.list_prompts.side_effect = Exception("Prompt fetch failed")

        # Context managers
        mock_sse_cm = AsyncMock()
        mock_sse_cm.__aenter__.return_value = (MagicMock(), MagicMock())
        mock_sse_cm.__aexit__.return_value = None

        mock_client_cm = AsyncMock()
        mock_client_cm.__aenter__.return_value = mock_session
        mock_client_cm.__aexit__.return_value = None

        with patch("mcpgateway.services.gateway_service.sse_client", return_value=mock_sse_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=mock_client_cm):
                # Execute
                capabilities, tools, resources, prompts = await gateway_service._connect_to_sse_server_without_validation("http://test.com")

                # Should return empty lists for failed parts, not raise exception
                assert len(resources) == 0
                assert len(prompts) == 0
                assert capabilities["resources"] is True


class TestGatewayHealth:
    """Test suite for gateway health checks and auto-refresh logic."""

    @pytest.fixture
    def mock_db_session(self):
        mock_session = MagicMock()
        # Allow context manager usage
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        return mock_session

    @pytest.fixture
    def mock_gateway_health(self):
        """Gateway ready for health checks."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw-health-1"
        gw.name = "Health Gateway"
        gw.url = "http://health.test"
        gw.enabled = True
        gw.auth_type = None
        gw.last_refresh_at = datetime.now(timezone.utc) - timedelta(hours=1)
        gw.refresh_interval_seconds = 300
        gw.ca_certificate = None
        gw.ca_certificate_sig = None
        return gw

    @pytest.mark.asyncio
    async def test_check_health_batch_success(self, gateway_service, mock_gateway_health):
        """Test batch health check success."""
        gateways = [mock_gateway_health]

        # Mock single check to succeed
        gateway_service._check_single_gateway_health = AsyncMock(return_value=None)

        # Mock settings
        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.max_concurrent_health_checks = 5
            mock_settings.gateway_health_check_timeout = 5

            result = await gateway_service.check_health_of_gateways(gateways)
            assert result is True
            gateway_service._check_single_gateway_health.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_health_timeout(self, gateway_service, mock_gateway_health):
        """Test handling of health check timeout."""
        gateways = [mock_gateway_health]

        # Mock single check to sleep forever (simulating timeout)
        async def slow_check(*args, **kwargs):
            await asyncio.sleep(0.2)

        gateway_service._check_single_gateway_health = AsyncMock(side_effect=slow_check)
        gateway_service._handle_gateway_failure = AsyncMock()

        # Mock settings with very short timeout
        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.max_concurrent_health_checks = 5
            mock_settings.gateway_health_check_timeout = 0.01  # Ultra short timeout

            result = await gateway_service.check_health_of_gateways(gateways)

            assert result is True
            # Should have timed out and called failure handler
            gateway_service._handle_gateway_failure.assert_awaited_once_with(mock_gateway_health)

    @pytest.mark.asyncio
    async def test_health_triggers_auto_refresh(self, gateway_service, mock_gateway_health, mock_db_session):
        """Test that health check triggers auto-refresh when due."""
        # Setup: Auto-refresh ON, Refresh needed
        gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock()
        gateway_service.set_gateway_state = AsyncMock()
        gateway_service._get_refresh_lock = MagicMock()

        # Lock needs to be MagicMock for sync .locked(), but behave as AsyncMock for context manager
        lock = MagicMock()
        lock.locked.return_value = False
        lock.__aenter__ = AsyncMock(return_value=None)
        lock.__aexit__ = AsyncMock(return_value=None)

        gateway_service._get_refresh_lock.return_value = lock

        # Mock http client for health ping
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = MagicMock(status_code=200)

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.auto_refresh_servers = True
            mock_settings.gateway_auto_refresh_interval = 300
            # Ensure Ed25519 signing is disabled to simplify test
            mock_settings.enable_ed25519_signing = False
            mock_settings.httpx_admin_read_timeout = 5.0

            with patch("mcpgateway.services.http_client_service.get_isolated_http_client", return_value=mock_client):
                with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
                    # Mock DB lookup for last_seen update
                    session = mock_db_session.__enter__()
                    session.execute.return_value = _make_execute_result(scalar=mock_gateway_health)

                    await gateway_service._check_single_gateway_health(mock_gateway_health)

                    # Should call refresh
                    gateway_service._refresh_gateway_tools_resources_prompts.assert_awaited_once()
                    args, kwargs = gateway_service._refresh_gateway_tools_resources_prompts.call_args
                    assert kwargs["created_via"] == "health_check"

    @pytest.mark.asyncio
    async def test_health_skips_refresh_disabled(self, gateway_service, mock_gateway_health, mock_db_session):
        """Test that health check skips refresh if feature disabled."""
        gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock()

        # Mock http client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = MagicMock(status_code=200)

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.auto_refresh_servers = False  # Disabled
            mock_settings.enable_ed25519_signing = False
            mock_settings.httpx_admin_read_timeout = 5.0

            with patch("mcpgateway.services.http_client_service.get_isolated_http_client", return_value=mock_client):
                with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
                    session = mock_db_session.__enter__()
                    session.execute.return_value = _make_execute_result(scalar=mock_gateway_health)

                    await gateway_service._check_single_gateway_health(mock_gateway_health)

                    gateway_service._refresh_gateway_tools_resources_prompts.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_skips_refresh_throttled(self, gateway_service, mock_gateway_health, mock_db_session):
        """Test that health check skips refresh if done recently."""
        # Setup: Refreshed just now
        mock_gateway_health.last_refresh_at = datetime.now(timezone.utc)
        gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock()

        # Mock http client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = MagicMock(status_code=200)

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.auto_refresh_servers = True
            mock_settings.gateway_auto_refresh_interval = 300
            mock_settings.enable_ed25519_signing = False
            mock_settings.httpx_admin_read_timeout = 5.0

            with patch("mcpgateway.services.http_client_service.get_isolated_http_client", return_value=mock_client):
                with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
                    session = mock_db_session.__enter__()
                    session.execute.return_value = _make_execute_result(scalar=mock_gateway_health)

                    await gateway_service._check_single_gateway_health(mock_gateway_health)

                    gateway_service._refresh_gateway_tools_resources_prompts.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_skips_refresh_locked(self, gateway_service, mock_gateway_health, mock_db_session):
        """Test that health check skips refresh if lock is held."""
        gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock()

        lock = MagicMock()
        lock.locked.return_value = True  # Lock held!
        lock.__aenter__ = AsyncMock(return_value=None)
        lock.__aexit__ = AsyncMock(return_value=None)

        gateway_service._get_refresh_lock = MagicMock(return_value=lock)

        # Mock http client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = MagicMock(status_code=200)

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.auto_refresh_servers = True
            mock_settings.enable_ed25519_signing = False
            mock_settings.httpx_admin_read_timeout = 5.0

            with patch("mcpgateway.services.http_client_service.get_isolated_http_client", return_value=mock_client):
                with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
                    session = mock_db_session.__enter__()
                    session.execute.return_value = _make_execute_result(scalar=mock_gateway_health)

                    await gateway_service._check_single_gateway_health(mock_gateway_health)

                    gateway_service._refresh_gateway_tools_resources_prompts.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_redis_ping_failure(self, monkeypatch):
        import mcpgateway.services.gateway_service as gs

        monkeypatch.setattr(gs, "REDIS_AVAILABLE", True)
        monkeypatch.setattr(gs.settings, "cache_type", "redis")
        monkeypatch.setattr(gs.settings, "redis_url", "redis://localhost:6379")
        monkeypatch.setattr(gs.settings, "platform_admin_email", "admin@example.com")

        service = gs.GatewayService()
        service._event_service = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.ping.side_effect = Exception("boom")
        monkeypatch.setattr(gs, "get_redis_client", AsyncMock(return_value=mock_redis))

        with pytest.raises(ConnectionError):
            await service.initialize()

    @pytest.mark.asyncio
    async def test_shutdown_releases_redis_leader_failure(self):
        service = GatewayService()

        class DummyTask:
            def __init__(self):
                self.cancel_called = False

            def cancel(self):
                self.cancel_called = True

            def __await__(self):
                async def _raise():
                    raise asyncio.CancelledError

                return _raise().__await__()

        service._leader_heartbeat_task = DummyTask()
        service._redis_client = AsyncMock()
        service._redis_client.eval.side_effect = Exception("boom")
        service._leader_key = "leader-key"
        service._instance_id = "instance-id"
        service._http_client = SimpleNamespace(aclose=AsyncMock())
        service._event_service = SimpleNamespace(shutdown=AsyncMock())

        await service.shutdown()

        assert service._leader_heartbeat_task.cancel_called is True
        service._redis_client.eval.assert_awaited()


def test_check_gateway_uniqueness_team_dict_auth():
    service = GatewayService()
    existing = MagicMock()
    existing.auth_value = {"Authorization": "Bearer token"}
    existing.oauth_config = None

    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [existing]

    db = MagicMock()
    db.query.return_value = query

    result = service._check_gateway_uniqueness(
        db=db,
        url="http://example.com",
        auth_value={"Authorization": "Bearer token"},
        oauth_config=None,
        team_id="team-1",
        owner_email="owner@example.com",
        visibility="team",
    )
    assert result is existing


def test_check_gateway_uniqueness_private_skips_unknown_auth():
    service = GatewayService()
    existing = MagicMock()
    existing.auth_value = ["bad"]
    existing.oauth_config = None

    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [existing]

    db = MagicMock()
    db.query.return_value = query

    result = service._check_gateway_uniqueness(
        db=db,
        url="http://example.com",
        auth_value={"Authorization": "Bearer token"},
        oauth_config=None,
        team_id=None,
        owner_email="owner@example.com",
        visibility="private",
    )
    assert result is None


@pytest.mark.asyncio
async def test_register_gateway_team_conflict(gateway_service, monkeypatch):
    existing = MagicMock()
    existing.slug = "test-gateway"
    existing.enabled = True
    existing.id = 321
    existing.visibility = "team"

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(return_value=existing))

    gateway_create = GatewayCreate(
        name="Test Gateway",
        url="http://example.com",
        description="Team gateway",
        visibility="team",
    )

    with pytest.raises(GatewayNameConflictError):
        await gateway_service.register_gateway(MagicMock(), gateway_create, team_id="team-1", visibility="team")


@pytest.mark.asyncio
async def test_register_gateway_auth_value_decode_failure(gateway_service, monkeypatch):
    gateway = _make_gateway(auth_value="bad-auth", auth_headers=[{"key": "X-API-Key", "value": "secret"}])

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.GatewayRead.model_validate",
        staticmethod(lambda x: MagicMock(masked=lambda: x)),
    )
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.decode_auth",
        lambda _val: (_ for _ in ()).throw(Exception("boom")),
    )
    monkeypatch.setattr("mcpgateway.services.gateway_service.encode_auth", lambda _val: "encoded")
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.GatewayRead.model_validate",
        lambda x: MagicMock(masked=lambda: x),
    )

    gateway_service._check_gateway_uniqueness = MagicMock(return_value=None)
    gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {}}, [], [], []))
    gateway_service._notify_gateway_added = AsyncMock()

    db = MagicMock()
    db.add = Mock()
    db.flush = Mock()
    db.refresh = Mock()

    await gateway_service.register_gateway(db, gateway)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_register_gateway_auth_headers_one_time_auth(gateway_service, monkeypatch):
    gateway = _make_gateway(auth_headers=[{"key": "X-API-Key", "value": "secret"}], one_time_auth=True)

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mcpgateway.services.gateway_service.encode_auth", lambda _val: "encoded")
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.GatewayRead.model_validate",
        lambda x: MagicMock(masked=lambda: x),
    )

    gateway_service._check_gateway_uniqueness = MagicMock(return_value=None)
    gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {}}, [], [], []))
    gateway_service._notify_gateway_added = AsyncMock()

    db = MagicMock()
    db.add = Mock()
    db.flush = Mock()
    db.refresh = Mock()

    await gateway_service.register_gateway(db, gateway)

    added_gateway = db.add.call_args[0][0]
    assert added_gateway.auth_type == "one_time_auth"
    assert added_gateway.auth_value is None


@pytest.mark.asyncio
async def test_register_gateway_query_param_timeout(gateway_service, monkeypatch):
    gateway = _make_gateway(auth_type="query_param", auth_query_param_key="api_key", auth_query_param_value=123)

    async def _fake_wait_for(coro, timeout):  # noqa: ARG001
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mcpgateway.services.gateway_service.encode_auth", lambda _val: "encrypted")
    monkeypatch.setattr("mcpgateway.services.gateway_service.apply_query_param_auth", lambda url, _params: f"{url}?api_key=123")
    monkeypatch.setattr("mcpgateway.services.gateway_service.asyncio.wait_for", _fake_wait_for)

    gateway_service._check_gateway_uniqueness = MagicMock(return_value=None)
    gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {}}, [], [], []))

    with pytest.raises(GatewayConnectionError):
        await gateway_service.register_gateway(MagicMock(), gateway, initialize_timeout=0.01)


@pytest.mark.asyncio
async def test_register_gateway_reassigns_orphaned_resource(gateway_service, monkeypatch):
    from mcpgateway.schemas import PromptCreate, ResourceCreate

    gateway = _make_gateway()
    resource = ResourceCreate(
        uri="https://example.com/resource.txt",
        name="Resource",
        description="Test resource",
        content="hello",
    )
    prompt = PromptCreate(name="Prompt", description="Test prompt", template="Hello")

    existing = MagicMock()
    existing.gateway_id = None
    existing.team_id = "team-1"
    existing.owner_email = "owner@example.com"
    existing.uri = resource.uri
    existing_prompt = MagicMock()
    existing_prompt.gateway_id = None
    existing_prompt.team_id = "team-1"
    existing_prompt.owner_email = "owner@example.com"
    existing_prompt.name = prompt.name

    result_ids = MagicMock()
    result_ids.all.return_value = [(1,), (2,)]

    result_resources = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = [existing]
    result_resources.scalars.return_value = scalars_proxy
    result_prompt_ids = MagicMock()
    result_prompt_ids.all.return_value = [(1,), (2,)]
    result_prompts = MagicMock()
    scalars_prompt = MagicMock()
    scalars_prompt.all.return_value = [existing_prompt]
    result_prompts.scalars.return_value = scalars_prompt

    db = MagicMock()
    db.execute = Mock(side_effect=[result_ids, result_resources, result_prompt_ids, result_prompts])
    db.add = Mock()
    db.flush = Mock()
    db.refresh = Mock()

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.GatewayRead.model_validate",
        lambda x: MagicMock(masked=lambda: x),
    )

    gateway_service._check_gateway_uniqueness = MagicMock(return_value=None)
    gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {}}, [], [resource], [prompt]))
    gateway_service._notify_gateway_added = AsyncMock()

    await gateway_service.register_gateway(
        db,
        gateway,
        team_id="team-1",
        owner_email="owner@example.com",
        created_by="creator@example.com",
    )

    added_gateway = db.add.call_args[0][0]
    assert existing in added_gateway.resources
    assert existing_prompt in added_gateway.prompts


def test_validate_tools_mixed_errors(monkeypatch):
    service = GatewayService()
    from mcpgateway.schemas import ToolCreate

    validation_error = None
    try:
        ToolCreate.model_validate({})
    except ValidationError as exc:
        validation_error = exc
    assert validation_error is not None

    def _validate(tool_dict):
        if tool_dict["name"] == "ok":
            return MagicMock()
        raise validation_error

    monkeypatch.setattr("mcpgateway.services.gateway_service.ToolCreate.model_validate", _validate)

    tools, errors = service._validate_tools([{"name": "ok"}, {"name": "bad"}])
    assert len(tools) == 1
    assert errors


def test_validate_tools_all_invalid_default(monkeypatch):
    service = GatewayService()
    from mcpgateway.schemas import ToolCreate

    validation_error = None
    try:
        ToolCreate.model_validate({})
    except ValidationError as exc:
        validation_error = exc
    assert validation_error is not None
    monkeypatch.setattr("mcpgateway.services.gateway_service.ToolCreate.model_validate", lambda _tool: (_ for _ in ()).throw(validation_error))

    with pytest.raises(GatewayConnectionError):
        service._validate_tools([{"name": "bad"}])


def test_validate_tools_all_invalid_oauth(monkeypatch):
    service = GatewayService()
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.ToolCreate.model_validate",
        lambda _tool: (_ for _ in ()).throw(ValueError("JSON structure exceeds maximum depth")),
    )

    with pytest.raises(OAuthToolValidationError):
        service._validate_tools([{"name": "bad"}], context="oauth")


def test_gateway_service_singleton_and_cache_helpers(monkeypatch):
    import mcpgateway.services.gateway_service as gs

    gs._gateway_service_instance = None
    instance = gs.gateway_service
    assert isinstance(instance, GatewayService)
    assert gs.gateway_service is instance

    with pytest.raises(AttributeError):
        getattr(gs, "missing_attr")

    registry_sentinel = SimpleNamespace(
        invalidate_tools=AsyncMock(),
        invalidate_resources=AsyncMock(),
        invalidate_prompts=AsyncMock(),
        invalidate_gateways=AsyncMock(),
    )
    tool_sentinel = SimpleNamespace(invalidate_gateway=AsyncMock())
    gs._REGISTRY_CACHE = None
    gs._TOOL_LOOKUP_CACHE = None

    monkeypatch.setitem(sys.modules, "mcpgateway.cache.registry_cache", SimpleNamespace(registry_cache=registry_sentinel))
    monkeypatch.setitem(sys.modules, "mcpgateway.cache.tool_lookup_cache", SimpleNamespace(tool_lookup_cache=tool_sentinel))

    assert gs._get_registry_cache() is registry_sentinel
    assert gs._get_tool_lookup_cache() is tool_sentinel


@pytest.mark.asyncio
async def test_connect_to_sse_server_without_validation_fallbacks(monkeypatch):
    from mcpgateway.schemas import PromptCreate, ResourceCreate

    service = GatewayService()
    service._validate_tools = MagicMock(return_value=([], []))

    class DummyUrl:
        def __init__(self, value):
            self.unicode_string = value

        def __str__(self):
            return self.unicode_string

    class DummyResponse:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class DummyTool:
        def model_dump(self, **_kwargs):
            return {"name": "tool-1", "description": "tool"}

    class DummyResource:
        def model_dump(self, **_kwargs):
            return {"uri": DummyUrl("https://example.com/resource.txt"), "name": "bad-resource"}

    class DummyTemplate:
        def model_dump(self, **_kwargs):
            return {"uriTemplate": DummyUrl("https://example.com/{id}"), "name": "tmpl"}

    class DummyPrompt:
        def model_dump(self, **_kwargs):
            return {"name": "bad-prompt"}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            capabilities = SimpleNamespace(model_dump=lambda **_kw: {"resources": True, "prompts": True})
            return DummyResponse(capabilities=capabilities)

        async def list_tools(self):
            return DummyResponse(tools=[DummyTool()])

        async def list_resources(self):
            return DummyResponse(resources=[DummyResource()])

        async def list_resource_templates(self):
            return DummyResponse(resourceTemplates=[DummyTemplate()])

        async def list_prompts(self):
            return DummyResponse(prompts=[DummyPrompt()])

    class DummySSE:
        async def __aenter__(self):
            return ("recv", "send")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    real_resource_validate = ResourceCreate.model_validate
    real_prompt_validate = PromptCreate.model_validate

    def _resource_validate(data):
        if data.get("name") == "bad-resource":
            raise ValueError("boom")
        return real_resource_validate(data)

    def _prompt_validate(data):
        if data.get("name") == "bad-prompt":
            raise ValueError("boom")
        return real_prompt_validate(data)

    monkeypatch.setattr("mcpgateway.services.gateway_service.sse_client", lambda **_kw: DummySSE())
    monkeypatch.setattr("mcpgateway.services.gateway_service.ClientSession", lambda *_args: DummySession())
    monkeypatch.setattr("mcpgateway.services.gateway_service.ResourceCreate.model_validate", _resource_validate)
    monkeypatch.setattr("mcpgateway.services.gateway_service.PromptCreate.model_validate", _prompt_validate)

    capabilities, tools, resources, prompts = await service._connect_to_sse_server_without_validation("http://server")

    assert capabilities["resources"] is True
    assert tools == []
    assert resources
    assert prompts


@pytest.mark.asyncio
async def test_connect_to_sse_server_without_validation_error(monkeypatch):
    service = GatewayService()

    class DummySSE:
        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.gateway_service.sse_client", lambda **_kw: DummySSE())

    with pytest.raises(GatewayConnectionError):
        await service._connect_to_sse_server_without_validation("http://server")


@pytest.mark.asyncio
async def test_connect_to_streamablehttp_server_resources_and_prompts(monkeypatch):
    from mcpgateway.schemas import PromptCreate, ResourceCreate

    service = GatewayService()
    tool_obj = SimpleNamespace(request_type="GET")
    service._validate_tools = MagicMock(return_value=([tool_obj], []))

    class DummyUrl:
        def __init__(self, value):
            self.unicode_string = value

        def __str__(self):
            return self.unicode_string

    class DummyResponse:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class DummyTool:
        def model_dump(self, **_kwargs):
            return {"name": "tool-1", "description": "tool"}

    class DummyResource:
        def model_dump(self, **_kwargs):
            return {"uri": DummyUrl("https://example.com/resource.txt"), "name": "bad-resource"}

    class DummyTemplate:
        def model_dump(self, **_kwargs):
            return {"uriTemplate": DummyUrl("https://example.com/{id}"), "name": "tmpl"}

    class DummyPrompt:
        def model_dump(self, **_kwargs):
            return {"name": "prompt", "template": "Hi"}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            capabilities = SimpleNamespace(model_dump=lambda **_kw: {"resources": True, "prompts": True})
            return DummyResponse(capabilities=capabilities)

        async def list_tools(self):
            return DummyResponse(tools=[DummyTool()])

        async def list_resources(self):
            return DummyResponse(resources=[DummyResource()])

        async def list_resource_templates(self):
            return DummyResponse(resourceTemplates=[DummyTemplate()])

        async def list_prompts(self):
            return DummyResponse(prompts=[DummyPrompt()])

    class DummyStreamable:
        def __init__(self, **kwargs):
            factory = kwargs.get("httpx_client_factory")
            if factory:
                factory()

        async def __aenter__(self):
            return ("read", "write", lambda: "session")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    real_resource_validate = ResourceCreate.model_validate

    def _resource_validate(data):
        if data.get("name") == "bad-resource":
            raise ValueError("boom")
        return real_resource_validate(data)

    monkeypatch.setattr("mcpgateway.services.gateway_service.httpx.AsyncClient", lambda **_kw: SimpleNamespace())
    monkeypatch.setattr("mcpgateway.services.gateway_service.get_default_verify", lambda: None)
    monkeypatch.setattr("mcpgateway.services.gateway_service.get_http_timeout", lambda: None)
    monkeypatch.setattr(service, "create_ssl_context", MagicMock(return_value="ctx"))
    monkeypatch.setattr("mcpgateway.services.gateway_service.streamablehttp_client", lambda **kw: DummyStreamable(**kw))
    monkeypatch.setattr("mcpgateway.services.gateway_service.ClientSession", lambda *_args: DummySession())
    monkeypatch.setattr("mcpgateway.services.gateway_service.ResourceCreate.model_validate", _resource_validate)

    capabilities, tools, resources, prompts = await service.connect_to_streamablehttp_server("http://server", ca_certificate=b"cert")

    assert capabilities["resources"] is True
    assert tool_obj.request_type == "STREAMABLEHTTP"
    assert resources
    assert prompts


@pytest.mark.asyncio
async def test_connect_to_streamablehttp_server_error_path(monkeypatch):
    service = GatewayService()

    class DummySession:
        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyStreamable:
        async def __aenter__(self):
            return ("read", "write", lambda: "session")

        async def __aexit__(self, exc_type, exc, tb):
            return True

    monkeypatch.setattr("mcpgateway.services.gateway_service.streamablehttp_client", lambda **_kw: DummyStreamable())
    monkeypatch.setattr("mcpgateway.services.gateway_service.ClientSession", lambda *_args: DummySession())

    with pytest.raises(GatewayConnectionError):
        await service.connect_to_streamablehttp_server("http://server")


@pytest.mark.asyncio
async def test_connect_to_sse_server_resources_and_prompts(monkeypatch):
    from mcpgateway.schemas import PromptCreate, ResourceCreate

    service = GatewayService()
    service._validate_tools = MagicMock(return_value=([], []))

    class DummyUrl:
        def __init__(self, value):
            self.unicode_string = value

        def __str__(self):
            return self.unicode_string

    class DummyResponse:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class DummyTool:
        def model_dump(self, **_kwargs):
            return {"name": "tool-1", "description": "tool"}

    class DummyResource:
        def model_dump(self, **_kwargs):
            return {"uri": DummyUrl("https://example.com/resource.txt"), "name": "bad-resource"}

    class DummyTemplate:
        def model_dump(self, **_kwargs):
            return {"uriTemplate": DummyUrl("https://example.com/{id}"), "name": "tmpl"}

    class DummyPrompt:
        def model_dump(self, **_kwargs):
            return {"name": "bad-prompt"}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            capabilities = SimpleNamespace(model_dump=lambda **_kw: {"resources": True, "prompts": True})
            return DummyResponse(capabilities=capabilities)

        async def list_tools(self):
            return DummyResponse(tools=[DummyTool()])

        async def list_resources(self):
            return DummyResponse(resources=[DummyResource()])

        async def list_resource_templates(self):
            return DummyResponse(resourceTemplates=[DummyTemplate()])

        async def list_prompts(self):
            return DummyResponse(prompts=[DummyPrompt()])

    class DummySSE:
        async def __aenter__(self):
            return ("recv", "send")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    real_resource_validate = ResourceCreate.model_validate
    real_prompt_validate = PromptCreate.model_validate

    def _resource_validate(data):
        if data.get("name") == "bad-resource":
            raise ValueError("boom")
        return real_resource_validate(data)

    def _prompt_validate(data):
        if data.get("name") == "bad-prompt":
            raise ValueError("boom")
        return real_prompt_validate(data)

    monkeypatch.setattr("mcpgateway.services.gateway_service.sse_client", lambda **_kw: DummySSE())
    monkeypatch.setattr("mcpgateway.services.gateway_service.ClientSession", lambda *_args: DummySession())
    monkeypatch.setattr("mcpgateway.services.gateway_service.ResourceCreate.model_validate", _resource_validate)
    monkeypatch.setattr("mcpgateway.services.gateway_service.PromptCreate.model_validate", _prompt_validate)

    capabilities, tools, resources, prompts = await service.connect_to_sse_server("http://server")

    assert capabilities["resources"] is True
    assert tools == []
    assert resources
    assert prompts


@pytest.mark.asyncio
async def test_connect_to_sse_server_error_path(monkeypatch):
    service = GatewayService()

    class DummySession:
        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummySSE:
        async def __aenter__(self):
            return ("recv", "send")

        async def __aexit__(self, exc_type, exc, tb):
            return True

    monkeypatch.setattr("mcpgateway.services.gateway_service.sse_client", lambda **_kw: DummySSE())
    monkeypatch.setattr("mcpgateway.services.gateway_service.ClientSession", lambda *_args: DummySession())

    with pytest.raises(GatewayConnectionError):
        await service.connect_to_sse_server("http://server")


@pytest.mark.asyncio
async def test_register_gateway_creates_new_resources_and_prompts(gateway_service, monkeypatch):
    from mcpgateway.schemas import PromptCreate, ResourceCreate

    gateway = _make_gateway(auth_value={"Authorization": "Bearer token"})
    resource = ResourceCreate(uri="https://example.com/resource.txt", name="Resource", description="Test resource", content="hello")
    prompt = PromptCreate(name="Prompt", description="Test prompt", template="Hello")

    result_ids = MagicMock()
    result_ids.all.return_value = []
    result_resources = _make_execute_result(scalars_list=[])
    result_prompt_ids = MagicMock()
    result_prompt_ids.all.return_value = []
    result_prompts = _make_execute_result(scalars_list=[])

    db = MagicMock()
    db.execute = Mock(side_effect=[result_ids, result_resources, result_prompt_ids, result_prompts])
    db.add = Mock()
    db.flush = Mock()
    db.refresh = Mock()

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.GatewayRead.model_validate",
        lambda x: MagicMock(masked=lambda: x),
    )

    gateway_service._check_gateway_uniqueness = MagicMock(return_value=None)
    gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {}}, [], [resource], [prompt]))
    gateway_service._notify_gateway_added = AsyncMock()

    await gateway_service.register_gateway(
        db,
        gateway,
        team_id="team-1",
        owner_email="owner@example.com",
        created_by="creator@example.com",
    )

    added_gateway = db.add.call_args[0][0]
    assert len(added_gateway.resources) == 1
    assert len(added_gateway.prompts) == 1


@pytest.mark.asyncio
async def test_shutdown_releases_redis_leader_success():
    service = GatewayService()
    service._redis_client = AsyncMock()
    service._redis_client.eval.return_value = 1
    service._leader_key = "leader-key"
    service._instance_id = "instance-id"
    service._http_client = SimpleNamespace(aclose=AsyncMock())
    service._event_service = SimpleNamespace(shutdown=AsyncMock())

    await service.shutdown()

    service._redis_client.eval.assert_awaited()


@pytest.mark.asyncio
async def test_fetch_tools_after_oauth_gateway_missing(gateway_service):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(GatewayConnectionError):
        await gateway_service.fetch_tools_after_oauth(db, "missing", "user@example.com")


@pytest.mark.asyncio
async def test_fetch_tools_after_oauth_missing_oauth_config(gateway_service):
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "gw-1"
    gateway.oauth_config = None
    gateway.transport = "sse"

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway
    db.execute.return_value = result

    with pytest.raises(GatewayConnectionError):
        await gateway_service.fetch_tools_after_oauth(db, "gw-1", "user@example.com")


@pytest.mark.asyncio
async def test_fetch_tools_after_oauth_missing_user_email(gateway_service, monkeypatch):
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "gw-1"
    gateway.name = "gw"
    gateway.oauth_config = {"grant_type": "authorization_code"}
    gateway.transport = "sse"

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway
    db.execute.return_value = result

    class DummyTokenStorage:
        def __init__(self, _db):
            self.db = _db

    monkeypatch.setattr("mcpgateway.services.token_storage_service.TokenStorageService", DummyTokenStorage)

    with pytest.raises(GatewayConnectionError):
        await gateway_service.fetch_tools_after_oauth(db, "gw-1", "")


@pytest.mark.asyncio
async def test_fetch_tools_after_oauth_unsupported_transport(gateway_service, monkeypatch):
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "gw-1"
    gateway.name = "gw"
    gateway.oauth_config = {"grant_type": "authorization_code"}
    gateway.transport = "grpc"

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway
    db.execute.return_value = result

    class DummyTokenStorage:
        def __init__(self, _db):
            self.db = _db

        async def get_user_token(self, _gateway_id, _email):
            return "token"

    monkeypatch.setattr("mcpgateway.services.token_storage_service.TokenStorageService", DummyTokenStorage)

    with pytest.raises(GatewayConnectionError):
        await gateway_service.fetch_tools_after_oauth(db, "gw-1", "user@example.com")


@pytest.mark.asyncio
async def test_fetch_tools_after_oauth_streamablehttp(gateway_service, monkeypatch):
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "gw-1"
    gateway.name = "gw"
    gateway.oauth_config = {"grant_type": "authorization_code"}
    gateway.transport = "streamablehttp"
    gateway.tools = []
    gateway.resources = []
    gateway.prompts = []

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway
    db.execute.return_value = result
    db.add_all = Mock()
    db.flush = Mock()
    db.commit = Mock()
    db.expire = Mock()

    class DummyTokenStorage:
        def __init__(self, _db):
            self.db = _db

        async def get_user_token(self, _gateway_id, _email):
            return "token"

    monkeypatch.setattr("mcpgateway.services.token_storage_service.TokenStorageService", DummyTokenStorage)
    gateway_service.connect_to_streamablehttp_server = AsyncMock(return_value=({"tools": {}}, [], [], []))
    gateway_service._update_or_create_tools = MagicMock(return_value=[])
    gateway_service._update_or_create_resources = MagicMock(return_value=[])
    gateway_service._update_or_create_prompts = MagicMock(return_value=[])

    registry_cache = SimpleNamespace(
        invalidate_tools=AsyncMock(),
        invalidate_resources=AsyncMock(),
        invalidate_prompts=AsyncMock(),
    )
    tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

    result_data = await gateway_service.fetch_tools_after_oauth(db, "gw-1", "user@example.com")

    assert "capabilities" in result_data


@pytest.mark.asyncio
async def test_fetch_tools_after_oauth_cleanup_and_adds_items(gateway_service, monkeypatch):
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "gw-1"
    gateway.name = "gw"
    gateway.oauth_config = {"grant_type": "authorization_code"}
    gateway.transport = "sse"
    gateway.tools = [SimpleNamespace(id=1, original_name="old-tool"), SimpleNamespace(id=2, original_name="keep-tool")]
    gateway.resources = [SimpleNamespace(id=3, uri="old://res"), SimpleNamespace(id=4, uri="keep://res")]
    gateway.prompts = [SimpleNamespace(id=5, original_name="old-prompt"), SimpleNamespace(id=6, original_name="keep-prompt")]
    gateway.capabilities = {}
    gateway.last_seen = None

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway
    db.execute.return_value = result
    db.add_all = Mock()
    db.flush = Mock()
    db.commit = Mock()
    db.expire = Mock()

    class DummyTokenStorage:
        def __init__(self, _db):
            self.db = _db

        async def get_user_token(self, _gateway_id, _email):
            return "Z0FBQUFBQmTOKEN"

    monkeypatch.setattr("mcpgateway.services.token_storage_service.TokenStorageService", DummyTokenStorage)
    gateway_service._connect_to_sse_server_without_validation = AsyncMock(
        return_value=({"resources": True, "prompts": True}, [SimpleNamespace(name="keep-tool")], [SimpleNamespace(uri="keep://res")], [SimpleNamespace(name="keep-prompt")])
    )
    gateway_service._update_or_create_tools = MagicMock(return_value=[MagicMock()])
    gateway_service._update_or_create_resources = MagicMock(return_value=[MagicMock()])
    gateway_service._update_or_create_prompts = MagicMock(return_value=[MagicMock()])

    registry_cache = SimpleNamespace(
        invalidate_tools=AsyncMock(),
        invalidate_resources=AsyncMock(),
        invalidate_prompts=AsyncMock(),
    )
    tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

    result_data = await gateway_service.fetch_tools_after_oauth(db, "gw-1", "user@example.com")

    assert result_data["capabilities"]["resources"] is True
    assert len(gateway.tools) == 1
    assert len(gateway.resources) == 1
    assert len(gateway.prompts) == 1


# ---------------------------------------------------------------------------
# Notification method tests
# ---------------------------------------------------------------------------


class TestNotificationMethods:
    """Tests for gateway notification methods."""

    @pytest.mark.asyncio
    async def test_notify_gateway_added(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        gw = _make_gateway(id=1, name="test", url="http://example.com", description="desc", enabled=True)
        await gateway_service._notify_gateway_added(gw)
        gateway_service._event_service.publish_event.assert_awaited_once()
        event = gateway_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "gateway_added"
        assert event["data"]["name"] == "test"

    @pytest.mark.asyncio
    async def test_notify_gateway_updated(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        gw = _make_gateway(id=1, name="updated", url="http://example.com", description="desc", enabled=True)
        await gateway_service._notify_gateway_updated(gw)
        gateway_service._event_service.publish_event.assert_awaited_once()
        event = gateway_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "gateway_updated"

    @pytest.mark.asyncio
    async def test_notify_gateway_deleted(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        info = {"id": 1, "name": "deleted-gw"}
        await gateway_service._notify_gateway_deleted(info)
        gateway_service._event_service.publish_event.assert_awaited_once()
        event = gateway_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "gateway_deleted"
        assert event["data"]["name"] == "deleted-gw"

    @pytest.mark.asyncio
    async def test_notify_gateway_activated(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        gw = _make_gateway(id=1, enabled=True, reachable=True)
        await gateway_service._notify_gateway_activated(gw)
        event = gateway_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "gateway_activated"

    @pytest.mark.asyncio
    async def test_notify_gateway_deactivated(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        gw = _make_gateway(id=1, enabled=False, reachable=False)
        await gateway_service._notify_gateway_deactivated(gw)
        event = gateway_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "gateway_deactivated"

    @pytest.mark.asyncio
    async def test_notify_gateway_offline(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        gw = _make_gateway(id=1, enabled=True, reachable=False)
        await gateway_service._notify_gateway_offline(gw)
        event = gateway_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "gateway_offline"
        assert event["data"]["enabled"] is True
        assert event["data"]["reachable"] is False

    @pytest.mark.asyncio
    async def test_notify_gateway_removed(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        gw = _make_gateway(id=1, enabled=False)
        await gateway_service._notify_gateway_removed(gw)
        event = gateway_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "gateway_removed"

    @pytest.mark.asyncio
    async def test_publish_event(self, gateway_service):
        gateway_service._event_service = AsyncMock()
        test_event = {"type": "test", "data": {"foo": "bar"}}
        await gateway_service._publish_event(test_event)
        gateway_service._event_service.publish_event.assert_awaited_once_with(test_event)


# ---------------------------------------------------------------------------
# Aggregate capabilities tests
# ---------------------------------------------------------------------------


class TestAggregateCapabilities:
    @pytest.mark.asyncio
    async def test_aggregate_capabilities_empty(self, gateway_service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        result = await gateway_service.aggregate_capabilities(db)
        assert "tools" in result
        assert "prompts" in result
        assert "resources" in result
        assert result["tools"]["listChanged"] is True

    @pytest.mark.asyncio
    async def test_aggregate_capabilities_merge(self, gateway_service):
        gw1 = SimpleNamespace(capabilities={"tools": {"feature1": True}, "custom": {"flag": True}})
        gw2 = SimpleNamespace(capabilities={"tools": {"feature2": True}})
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [gw1, gw2]
        result = await gateway_service.aggregate_capabilities(db)
        assert result["tools"]["listChanged"] is True
        assert result["tools"]["feature1"] is True
        assert result["tools"]["feature2"] is True
        assert result["custom"]["flag"] is True

    @pytest.mark.asyncio
    async def test_aggregate_capabilities_none_caps(self, gateway_service):
        gw = SimpleNamespace(capabilities=None)
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [gw]
        result = await gateway_service.aggregate_capabilities(db)
        # Should still have defaults
        assert "tools" in result


# ---------------------------------------------------------------------------
# Subscribe events test
# ---------------------------------------------------------------------------


class TestSubscribeEvents:
    @pytest.mark.asyncio
    async def test_subscribe_events(self, gateway_service):
        async def mock_event_gen():
            yield {"type": "gateway_added", "data": {"id": 1}}
            yield {"type": "gateway_deleted", "data": {"id": 2}}

        gateway_service._event_service = MagicMock()
        gateway_service._event_service.subscribe_events.return_value = mock_event_gen()

        events = []
        async for event in gateway_service.subscribe_events():
            events.append(event)

        assert len(events) == 2
        assert events[0]["type"] == "gateway_added"
        assert events[1]["type"] == "gateway_deleted"


# ---------------------------------------------------------------------------
# Tool validation tests
# ---------------------------------------------------------------------------


class TestValidateTools:
    def test_validate_tools_success(self, gateway_service):
        tools = [{"name": "test_tool", "description": "A test tool", "inputSchema": {"type": "object"}}]
        valid_tools, errors = gateway_service._validate_tools(tools)
        assert len(valid_tools) == 1
        assert len(errors) == 0

    def test_validate_tools_invalid(self, gateway_service):
        # Missing required 'name' field should cause validation error
        tools = [{"description": "No name tool"}]
        with pytest.raises(GatewayConnectionError):
            gateway_service._validate_tools(tools)

    def test_validate_tools_mixed(self, gateway_service):
        tools = [
            {"name": "good_tool", "description": "Valid tool", "inputSchema": {"type": "object"}},
            {"description": "Bad tool - no name"},  # Invalid
        ]
        valid_tools, errors = gateway_service._validate_tools(tools)
        assert len(valid_tools) == 1
        assert len(errors) == 1

    def test_validate_tools_all_fail_oauth_context(self, gateway_service):
        tools = [{"description": "Bad tool"}]
        with pytest.raises(OAuthToolValidationError):
            gateway_service._validate_tools(tools, context="oauth")

    def test_validate_tools_empty(self, gateway_service):
        valid_tools, errors = gateway_service._validate_tools([])
        assert len(valid_tools) == 0
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# Handle gateway failure tests
# ---------------------------------------------------------------------------


class TestHandleGatewayFailure:
    @pytest.mark.asyncio
    async def test_failure_counting(self, gateway_service):
        gw = SimpleNamespace(id="gw1", name="test", enabled=True, reachable=True)
        gateway_service._gateway_failure_counts = {}
        await gateway_service._handle_gateway_failure(gw)
        assert gateway_service._gateway_failure_counts["gw1"] == 1

    @pytest.mark.asyncio
    async def test_disabled_gateway_no_action(self, gateway_service):
        gw = SimpleNamespace(id="gw1", name="test", enabled=False, reachable=True)
        gateway_service._gateway_failure_counts = {}
        await gateway_service._handle_gateway_failure(gw)
        assert "gw1" not in gateway_service._gateway_failure_counts

    @pytest.mark.asyncio
    async def test_unreachable_gateway_no_action(self, gateway_service):
        gw = SimpleNamespace(id="gw1", name="test", enabled=True, reachable=False)
        gateway_service._gateway_failure_counts = {}
        await gateway_service._handle_gateway_failure(gw)
        assert "gw1" not in gateway_service._gateway_failure_counts


# ---------------------------------------------------------------------------
# _prepare_gateway_for_read tests (deprecated but still exercised)
# ---------------------------------------------------------------------------


class TestPrepareGatewayForRead:
    def test_prepare_gateway_encodes_dict_auth(self, gateway_service, mock_gateway):
        mock_gateway.auth_value = {"Authorization": "Bearer token"}
        mock_gateway.tags = []
        result = gateway_service._prepare_gateway_for_read(mock_gateway)
        # Auth value should be encoded as string now
        assert isinstance(result.auth_value, str)

    def test_prepare_gateway_converts_string_tags(self, gateway_service, mock_gateway):
        mock_gateway.tags = ["tag1", "tag2"]
        mock_gateway.auth_value = None
        result = gateway_service._prepare_gateway_for_read(mock_gateway)
        # Tags should be converted from List[str] to List[Dict]
        assert isinstance(result.tags[0], dict)


# ---------------------------------------------------------------------------
# _get_auth_headers test
# ---------------------------------------------------------------------------


class TestGetAuthHeaders:
    def test_returns_content_type_only(self, gateway_service):
        headers = gateway_service._get_auth_headers()
        assert headers == {"Content-Type": "application/json"}
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# normalize_url test
# ---------------------------------------------------------------------------


class TestNormalizeUrl:
    def test_normalize_preserves_domain(self):
        result = GatewayService.normalize_url("http://EXAMPLE.COM/path/")
        assert result == "http://EXAMPLE.COM/path/"

    def test_normalize_127_to_localhost(self):
        result = GatewayService.normalize_url("http://127.0.0.1:8080/path")
        assert result == "http://localhost:8080/path"

    def test_normalize_preserves_https(self):
        result = GatewayService.normalize_url("https://example.com/api")
        assert result == "https://example.com/api"


# ---------------------------------------------------------------------------
# _update_or_create_tools tests
# ---------------------------------------------------------------------------


class TestUpdateOrCreateTools:
    """Tests for _update_or_create_tools helper."""

    def test_empty_tools_returns_empty(self, gateway_service, mock_gateway):
        result = gateway_service._update_or_create_tools(MagicMock(), [], mock_gateway, "test")
        assert result == []

    def test_new_tool_created(self, gateway_service, mock_gateway):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []  # no existing
        tool = SimpleNamespace(
            name="new-tool", description="A new tool", input_schema={"type": "object"},
            output_schema=None, request_type="POST", headers={},
            annotations=None, jsonpath_filter=None,
        )
        mock_gateway.id = "gw-1"
        mock_gateway.auth_type = None
        mock_gateway.auth_value = None
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.owner_email = None
        fake_db_tool = MagicMock()
        gateway_service._create_db_tool = MagicMock(return_value=fake_db_tool)
        result = gateway_service._update_or_create_tools(db, [tool], mock_gateway, "test")
        assert len(result) == 1
        gateway_service._create_db_tool.assert_called_once()

    def test_existing_tool_updated(self, gateway_service, mock_gateway):
        existing = MagicMock()
        existing.original_name = "my-tool"
        existing.url = "http://old-url.com"
        existing.description = "old desc"
        existing.original_description = "old desc"
        existing.integration_type = "MCP"
        existing.request_type = "POST"
        existing.headers = {}
        existing.input_schema = {}
        existing.output_schema = None
        existing.jsonpath_filter = None
        existing.auth_type = None
        existing.auth_value = None
        existing.visibility = "public"

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [existing]

        tool = SimpleNamespace(
            name="my-tool", description="new desc", input_schema={},
            output_schema=None, request_type="POST", headers={},
            annotations=None, jsonpath_filter=None,
        )
        mock_gateway.url = "http://new-url.com"
        mock_gateway.auth_type = None
        mock_gateway.auth_value = None
        mock_gateway.visibility = "public"
        result = gateway_service._update_or_create_tools(db, [tool], mock_gateway, "update")
        assert result == []  # updated in-place, no new tools
        assert existing.url == "http://new-url.com"
        assert existing.description == "new desc"

    def test_none_tool_skipped(self, gateway_service, mock_gateway):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        tool = SimpleNamespace(
            name="good-tool", description="ok", input_schema={},
            output_schema=None, request_type="POST", headers={},
            annotations=None, jsonpath_filter=None,
        )
        mock_gateway.id = "gw-1"
        mock_gateway.auth_type = None
        mock_gateway.auth_value = None
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.owner_email = None
        gateway_service._create_db_tool = MagicMock(return_value=MagicMock())
        result = gateway_service._update_or_create_tools(db, [None, tool], mock_gateway, "test")
        assert len(result) == 1

    def test_tool_exception_continues(self, gateway_service, mock_gateway):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        bad_tool = SimpleNamespace(name="bad")  # will raise on _create_db_tool
        good_tool = SimpleNamespace(
            name="good-tool", description="ok", input_schema={},
            output_schema=None, request_type="POST", headers={},
            annotations=None, jsonpath_filter=None,
        )
        mock_gateway.id = "gw-1"
        mock_gateway.auth_type = None
        mock_gateway.auth_value = None
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.owner_email = None
        call_count = 0

        def _create_db_tool_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Missing fields")
            return MagicMock()

        gateway_service._create_db_tool = MagicMock(side_effect=_create_db_tool_side_effect)
        result = gateway_service._update_or_create_tools(db, [bad_tool, good_tool], mock_gateway, "test")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _update_or_create_resources tests
# ---------------------------------------------------------------------------


class TestUpdateOrCreateResources:
    def test_empty_resources_returns_empty(self, gateway_service, mock_gateway):
        result = gateway_service._update_or_create_resources(MagicMock(), [], mock_gateway, "test")
        assert result == []

    def test_new_resource_created(self, gateway_service, mock_gateway):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        resource = SimpleNamespace(
            uri="file:///new", name="new-res", description="A resource",
            mime_type="text/plain", uri_template=None,
        )
        mock_gateway.id = "gw-1"
        mock_gateway.visibility = "public"
        result = gateway_service._update_or_create_resources(db, [resource], mock_gateway, "test")
        assert len(result) == 1

    def test_existing_resource_updated(self, gateway_service, mock_gateway):
        existing = MagicMock()
        existing.uri = "file:///res"
        existing.name = "old-name"
        existing.description = "old"
        existing.mime_type = "text/plain"
        existing.uri_template = None
        existing.visibility = "public"
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [existing]
        resource = SimpleNamespace(
            uri="file:///res", name="new-name", description="new",
            mime_type="text/html", uri_template=None,
        )
        mock_gateway.visibility = "public"
        result = gateway_service._update_or_create_resources(db, [resource], mock_gateway, "update")
        assert result == []
        assert existing.name == "new-name"
        assert existing.mime_type == "text/html"

    def test_none_resource_skipped(self, gateway_service, mock_gateway):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        resource = SimpleNamespace(
            uri="file:///good", name="good", description="ok",
            mime_type="text/plain", uri_template=None,
        )
        mock_gateway.id = "gw-1"
        mock_gateway.visibility = "public"
        result = gateway_service._update_or_create_resources(db, [None, resource], mock_gateway, "test")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _update_or_create_prompts tests
# ---------------------------------------------------------------------------


class TestUpdateOrCreatePrompts:
    def test_empty_prompts_returns_empty(self, gateway_service, mock_gateway):
        result = gateway_service._update_or_create_prompts(MagicMock(), [], mock_gateway, "test")
        assert result == []

    def test_new_prompt_created(self, gateway_service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        prompt = SimpleNamespace(name="new-prompt", description="A prompt", template="Hello {name}")
        # Use non-spec'd MagicMock to allow _sa_instance_state assignment
        gw = MagicMock()
        gw.id = "gw-1"
        gw.visibility = "public"
        result = gateway_service._update_or_create_prompts(db, [prompt], gw, "test")
        assert len(result) == 1

    def test_existing_prompt_updated(self, gateway_service, mock_gateway):
        existing = MagicMock()
        existing.original_name = "my-prompt"
        existing.description = "old"
        existing.template = "old template"
        existing.visibility = "public"
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [existing]
        prompt = SimpleNamespace(name="my-prompt", description="new desc", template="new template")
        mock_gateway.visibility = "public"
        result = gateway_service._update_or_create_prompts(db, [prompt], mock_gateway, "update")
        assert result == []
        assert existing.description == "new desc"
        assert existing.template == "new template"

    def test_none_prompt_skipped(self, gateway_service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        prompt = SimpleNamespace(name="good-prompt", description="ok", template="Hi")
        gw = MagicMock()
        gw.id = "gw-1"
        gw.visibility = "public"
        result = gateway_service._update_or_create_prompts(db, [None, prompt], gw, "test")
        assert len(result) == 1

    def test_prompt_without_template(self, gateway_service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        prompt = SimpleNamespace(name="no-template", description="No template prompt")
        # no 'template' attribute → hasattr(prompt, "template") is False → defaults to ""
        gw = MagicMock()
        gw.id = "gw-1"
        gw.visibility = "public"
        result = gateway_service._update_or_create_prompts(db, [prompt], gw, "test")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# set_gateway_state tests
# ---------------------------------------------------------------------------


class TestSetGatewayState:
    """Tests for the set_gateway_state method."""

    @pytest.fixture
    def _mock_caches(self, monkeypatch):
        registry_cache = SimpleNamespace(
            invalidate_gateways=AsyncMock(),
            invalidate_tools=AsyncMock(),
            invalidate_resources=AsyncMock(),
            invalidate_prompts=AsyncMock(),
        )
        tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
        monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())
        return registry_cache, tool_lookup_cache

    def _make_db_for_state(self, gateway):
        """Create a mock DB that returns the gateway and supports bulk updates."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=gateway, rowcount=0)
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.expire = MagicMock()
        db.add_all = MagicMock()
        db.flush = MagicMock()
        db.rollback = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_activate_gateway(self, gateway_service, _mock_caches):
        gw = _make_gateway(
            id="gw-1", name="test", url="http://example.com", enabled=False,
            reachable=False, capabilities={}, tools=[], resources=[], prompts=[],
            updated_at=datetime.now(timezone.utc), team_id=None, slug="test",
            auth_type=None, auth_query_params=None, version=1,
        )
        db = self._make_db_for_state(gw)
        gateway_service._initialize_gateway = AsyncMock(
            return_value=({}, [], [], [])
        )
        gateway_service._event_service = AsyncMock()

        result = await gateway_service.set_gateway_state(db, "gw-1", activate=True, reachable=True)
        assert gw.enabled is True
        assert gw.reachable is True

    @pytest.mark.asyncio
    async def test_deactivate_gateway(self, gateway_service, _mock_caches):
        gw = _make_gateway(
            id="gw-1", name="test", url="http://example.com", enabled=True,
            reachable=True, capabilities={}, tools=[], resources=[], prompts=[],
            updated_at=datetime.now(timezone.utc), team_id=None, slug="test",
            auth_type=None, auth_query_params=None, version=1,
        )
        db = self._make_db_for_state(gw)
        gateway_service._event_service = AsyncMock()

        result = await gateway_service.set_gateway_state(db, "gw-1", activate=False, reachable=False)
        assert gw.enabled is False
        assert gw.reachable is False

    @pytest.mark.asyncio
    async def test_not_found(self, gateway_service, _mock_caches):
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=None)
        db.rollback = MagicMock()
        with pytest.raises(GatewayError, match="Gateway not found"):
            await gateway_service.set_gateway_state(db, "missing", activate=True)

    @pytest.mark.asyncio
    async def test_permission_error(self, gateway_service, _mock_caches, monkeypatch):
        gw = _make_gateway(
            id="gw-1", name="test", url="http://example.com", enabled=True,
            reachable=True, capabilities={}, tools=[], resources=[], prompts=[],
            updated_at=datetime.now(timezone.utc), team_id=None, slug="test",
            auth_type=None, auth_query_params=None, version=1,
        )
        db = self._make_db_for_state(gw)
        mock_perm = MagicMock()
        mock_perm.return_value.check_resource_ownership = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService", mock_perm)
        with pytest.raises(PermissionError):
            await gateway_service.set_gateway_state(db, "gw-1", activate=True, user_email="other@example.com")

    @pytest.mark.asyncio
    async def test_only_update_reachable(self, gateway_service, _mock_caches):
        gw = _make_gateway(
            id="gw-1", name="test", url="http://example.com", enabled=True,
            reachable=True, capabilities={}, tools=[], resources=[], prompts=[],
            updated_at=datetime.now(timezone.utc), team_id=None, slug="test",
            auth_type=None, auth_query_params=None, version=1,
        )
        db = self._make_db_for_state(gw)
        gateway_service._event_service = AsyncMock()

        result = await gateway_service.set_gateway_state(db, "gw-1", activate=True, reachable=False, only_update_reachable=True)
        assert gw.reachable is False

    @pytest.mark.asyncio
    async def test_no_state_change(self, gateway_service, _mock_caches):
        gw = _make_gateway(
            id="gw-1", name="test", url="http://example.com", enabled=True,
            reachable=True, capabilities={}, tools=[], resources=[], prompts=[],
            updated_at=datetime.now(timezone.utc), team_id=None, slug="test",
            auth_type=None, auth_query_params=None, version=1,
        )
        db = self._make_db_for_state(gw)
        # When state hasn't changed, should skip all the activation logic
        result = await gateway_service.set_gateway_state(db, "gw-1", activate=True, reachable=True)
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_activation_with_init_failure(self, gateway_service, _mock_caches):
        gw = _make_gateway(
            id="gw-1", name="test", url="http://example.com", enabled=False,
            reachable=False, capabilities={}, tools=[], resources=[], prompts=[],
            updated_at=datetime.now(timezone.utc), team_id=None, slug="test",
            auth_type=None, auth_query_params=None, version=1,
        )
        db = self._make_db_for_state(gw)
        gateway_service._initialize_gateway = AsyncMock(side_effect=Exception("Connection refused"))
        gateway_service._event_service = AsyncMock()

        # Should still activate even if initialization fails (logs warning)
        result = await gateway_service.set_gateway_state(db, "gw-1", activate=True, reachable=True)
        assert gw.enabled is True

    @pytest.mark.asyncio
    async def test_generic_exception_raises_gateway_error(self, gateway_service, _mock_caches):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("DB broken")
        db.rollback = MagicMock()
        with pytest.raises(GatewayError, match="Failed to set gateway state"):
            await gateway_service.set_gateway_state(db, "gw-1", activate=True)

    @pytest.mark.asyncio
    async def test_activate_with_query_param_auth(self, gateway_service, _mock_caches, monkeypatch):
        gw = _make_gateway(
            id="gw-1", name="test", url="http://example.com", enabled=False,
            reachable=False, capabilities={}, tools=[], resources=[], prompts=[],
            updated_at=datetime.now(timezone.utc), team_id=None, slug="test",
            auth_type="query_param",
            auth_query_params={"api_key": "encrypted_value"},
            version=1,
        )
        db = self._make_db_for_state(gw)
        # Mock decode_auth to return decrypted value
        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", lambda x: {"api_key": "secret123"})
        monkeypatch.setattr("mcpgateway.services.gateway_service.apply_query_param_auth", lambda url, params: url + "?api_key=secret123")
        gateway_service._initialize_gateway = AsyncMock(return_value=({}, [], [], []))
        gateway_service._event_service = AsyncMock()

        result = await gateway_service.set_gateway_state(db, "gw-1", activate=True, reachable=True)
        assert gw.enabled is True
        # Verify _initialize_gateway was called with query param URL
        call_args = gateway_service._initialize_gateway.call_args
        assert "secret123" in call_args[0][0]


# ---------------------------------------------------------------------------
# delete_gateway tests
# ---------------------------------------------------------------------------


class TestDeleteGateway:
    """Tests for the delete_gateway method."""

    @pytest.fixture
    def _mock_caches(self, monkeypatch):
        registry_cache = SimpleNamespace(invalidate_gateways=AsyncMock())
        tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        return registry_cache, tool_lookup_cache

    @pytest.mark.asyncio
    async def test_delete_gateway_success(self, gateway_service, _mock_caches):
        gw = MagicMock()
        gw.id = "gw-1"
        gw.name = "test-gw"
        gw.url = "http://example.com"
        gw.team_id = None
        gw.tools = []
        gw.resources = []
        gw.prompts = []

        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=gw, rowcount=1)
        db.commit = MagicMock()
        db.expire = MagicMock()
        gateway_service._event_service = AsyncMock()

        await gateway_service.delete_gateway(db, "gw-1")
        db.commit.assert_called()
        gateway_service._event_service.publish_event.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_gateway_not_found(self, gateway_service, _mock_caches):
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=None)
        db.rollback = MagicMock()
        with pytest.raises(GatewayError, match="Gateway not found"):
            await gateway_service.delete_gateway(db, "missing")

    @pytest.mark.asyncio
    async def test_delete_gateway_permission_error(self, gateway_service, _mock_caches, monkeypatch):
        gw = MagicMock()
        gw.id = "gw-1"
        gw.name = "test-gw"
        gw.url = "http://example.com"
        gw.team_id = None
        gw.tools = []
        gw.resources = []
        gw.prompts = []
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=gw)
        db.rollback = MagicMock()
        mock_perm = MagicMock()
        mock_perm.return_value.check_resource_ownership = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService", mock_perm)
        with pytest.raises(PermissionError):
            await gateway_service.delete_gateway(db, "gw-1", user_email="other@example.com")

    @pytest.mark.asyncio
    async def test_delete_gateway_with_children(self, gateway_service, _mock_caches):
        """Test deletion with tools, resources, and prompts to exercise chunked deletion."""
        tool = MagicMock()
        tool.id = "t1"
        resource = MagicMock()
        resource.id = "r1"
        prompt = MagicMock()
        prompt.id = "p1"
        gw = MagicMock()
        gw.id = "gw-1"
        gw.name = "gw-with-children"
        gw.url = "http://example.com"
        gw.team_id = None
        gw.tools = [tool]
        gw.resources = [resource]
        gw.prompts = [prompt]

        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=gw, rowcount=1)
        db.commit = MagicMock()
        db.expire = MagicMock()
        gateway_service._event_service = AsyncMock()

        await gateway_service.delete_gateway(db, "gw-1")
        # Should call execute multiple times for child deletion + gateway deletion
        assert db.execute.call_count > 1

    @pytest.mark.asyncio
    async def test_delete_gateway_generic_error(self, gateway_service, _mock_caches):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("DB exploded")
        db.rollback = MagicMock()
        with pytest.raises(GatewayError, match="Failed to delete gateway"):
            await gateway_service.delete_gateway(db, "gw-1")


# ---------------------------------------------------------------------------
# get_gateway tests
# ---------------------------------------------------------------------------


class TestGetGateway:
    @pytest.mark.asyncio
    async def test_get_gateway_success(self, gateway_service, mock_gateway):
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        result = await gateway_service.get_gateway(db, "gw-1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_gateway_not_found(self, gateway_service):
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=None)
        with pytest.raises(GatewayNotFoundError):
            await gateway_service.get_gateway(db, "missing")

    @pytest.mark.asyncio
    async def test_get_inactive_gateway_with_include(self, gateway_service, mock_gateway):
        mock_gateway.enabled = False
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        result = await gateway_service.get_gateway(db, "gw-1", include_inactive=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_inactive_gateway_without_include(self, gateway_service, mock_gateway):
        mock_gateway.enabled = False
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        with pytest.raises(GatewayNotFoundError):
            await gateway_service.get_gateway(db, "gw-1", include_inactive=False)


# ---------------------------------------------------------------------------
# update_gateway tests
# ---------------------------------------------------------------------------


class TestUpdateGateway:
    @pytest.fixture
    def _mock_caches(self, monkeypatch):
        registry_cache = SimpleNamespace(
            invalidate_gateways=AsyncMock(),
            invalidate_tools=AsyncMock(),
        )
        tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda db, model, *a, **kw: kw.get("where", None) or db._get_for_update_result)
        return registry_cache, tool_lookup_cache

    @pytest.mark.asyncio
    async def test_update_not_found(self, gateway_service, _mock_caches):
        db = MagicMock()
        db._get_for_update_result = None
        update = GatewayUpdate(name="updated")
        with pytest.raises(GatewayNotFoundError):
            await gateway_service.update_gateway(db, "missing", update)

    @pytest.mark.asyncio
    async def test_update_permission_error(self, gateway_service, _mock_caches, monkeypatch):
        gw = MagicMock()
        gw.id = "gw-1"
        gw.enabled = True
        gw.name = "test"
        db = MagicMock()
        db._get_for_update_result = gw
        mock_perm = MagicMock()
        mock_perm.return_value.check_resource_ownership = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService", mock_perm)
        db.rollback = MagicMock()

        update = GatewayUpdate(name="updated")
        with pytest.raises(PermissionError):
            await gateway_service.update_gateway(db, "gw-1", update, user_email="other@test.com")

    @pytest.mark.asyncio
    async def test_update_inactive_without_include(self, gateway_service, _mock_caches):
        gw = MagicMock()
        gw.id = "gw-1"
        gw.enabled = False
        db = MagicMock()
        db._get_for_update_result = gw

        update = GatewayUpdate(name="updated")
        result = await gateway_service.update_gateway(db, "gw-1", update, include_inactive=False)
        assert result is None


# ---------------------------------------------------------------------------
# _handle_gateway_failure - threshold tests
# ---------------------------------------------------------------------------


class TestHandleGatewayFailureThreshold:
    @pytest.mark.asyncio
    async def test_failure_threshold_reached(self, gateway_service, monkeypatch):
        """When failure count exceeds threshold, gateway should be marked unreachable."""
        gw = SimpleNamespace(id="gw-1", name="test", enabled=True, reachable=True)
        gateway_service._gateway_failure_counts = {}
        gateway_service._max_failures = 3
        # Accumulate failures just below threshold
        for _ in range(2):
            await gateway_service._handle_gateway_failure(gw)
        assert gateway_service._gateway_failure_counts["gw-1"] == 2

    @pytest.mark.asyncio
    async def test_failure_count_increments(self, gateway_service):
        gw = SimpleNamespace(id="gw-2", name="test2", enabled=True, reachable=True)
        gateway_service._gateway_failure_counts = {"gw-2": 1}
        await gateway_service._handle_gateway_failure(gw)
        assert gateway_service._gateway_failure_counts["gw-2"] == 2


# ---------------------------------------------------------------------------
# _check_single_gateway_health tests
# ---------------------------------------------------------------------------


class TestCheckSingleGatewayHealth:
    @pytest.mark.asyncio
    async def test_health_check_non_oauth_sse(self, gateway_service, monkeypatch):
        """Test SSE health check with non-OAuth auth."""
        gw = _make_gateway(
            id="gw-1", name="sse-gw", url="http://example.com/sse",
            enabled=True, reachable=True, transport="sse",
            auth_type="bearer", auth_value={"Authorization": "Bearer tok"},
            auth_query_params=None, ca_certificate=None,
            ca_certificate_sig=None, oauth_config=None,
            last_refresh_at=None, refresh_interval_seconds=None,
        )

        # Mock the isolated HTTP client context manager
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_stream_response = AsyncMock()
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream_response)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", lambda **kw: mock_ctx)
        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock())
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            enable_ed25519_signing=False, health_check_timeout=5,
            auto_refresh_servers=False, httpx_admin_read_timeout=5,
            mcp_session_pool_enabled=False,
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        await gateway_service._check_single_gateway_health(gw)

    @pytest.mark.asyncio
    async def test_health_check_failure(self, gateway_service, monkeypatch):
        """Test health check failure triggers _handle_gateway_failure."""
        gw = _make_gateway(
            id="gw-1", name="fail-gw", url="http://example.com",
            enabled=True, reachable=True, transport="sse",
            auth_type=None, auth_value=None,
            auth_query_params=None, ca_certificate=None,
            ca_certificate_sig=None, oauth_config=None,
            last_refresh_at=None, refresh_interval_seconds=None,
        )

        mock_client = MagicMock()
        mock_client.stream = MagicMock(side_effect=ConnectionError("refused"))

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", lambda **kw: mock_ctx)
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            enable_ed25519_signing=False, health_check_timeout=5,
            auto_refresh_servers=False, httpx_admin_read_timeout=5,
            mcp_session_pool_enabled=False,
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))
        gateway_service._handle_gateway_failure = AsyncMock()

        await gateway_service._check_single_gateway_health(gw)
        gateway_service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_oauth_client_credentials(self, gateway_service, monkeypatch):
        """Test health check with OAuth client_credentials auth."""
        gw = _make_gateway(
            id="gw-1", name="oauth-gw", url="http://example.com",
            enabled=True, reachable=True, transport="sse",
            auth_type="oauth", auth_value=None,
            auth_query_params=None, ca_certificate=None,
            ca_certificate_sig=None,
            oauth_config={"grant_type": "client_credentials", "token_url": "http://auth/token"},
            last_refresh_at=None, refresh_interval_seconds=None,
        )

        gateway_service.oauth_manager = AsyncMock()
        gateway_service.oauth_manager.get_access_token = AsyncMock(return_value="oauth-token")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_stream_response = AsyncMock()
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream_response)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", lambda **kw: mock_ctx)
        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock())
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            enable_ed25519_signing=False, health_check_timeout=5,
            auto_refresh_servers=False, httpx_admin_read_timeout=5,
            mcp_session_pool_enabled=False,
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        await gateway_service._check_single_gateway_health(gw)
        gateway_service.oauth_manager.get_access_token.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_oauth_client_creds_failure(self, gateway_service, monkeypatch):
        """Test health check with OAuth client_credentials token failure."""
        gw = _make_gateway(
            id="gw-1", name="oauth-fail-gw", url="http://example.com",
            enabled=True, reachable=True, transport="sse",
            auth_type="oauth", auth_value=None,
            auth_query_params=None, ca_certificate=None,
            ca_certificate_sig=None,
            oauth_config={"grant_type": "client_credentials"},
            last_refresh_at=None, refresh_interval_seconds=None,
        )
        gateway_service.oauth_manager = AsyncMock()
        gateway_service.oauth_manager.get_access_token = AsyncMock(side_effect=Exception("Token expired"))

        mock_client = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", lambda **kw: mock_ctx)
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            enable_ed25519_signing=False, health_check_timeout=5,
            auto_refresh_servers=False, httpx_admin_read_timeout=5,
            mcp_session_pool_enabled=False,
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))
        gateway_service._handle_gateway_failure = AsyncMock()

        await gateway_service._check_single_gateway_health(gw)
        gateway_service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_oauth_auth_code_no_user(self, gateway_service, monkeypatch):
        """Auth code OAuth without user_email → marks gateway unhealthy."""
        gw = _make_gateway(
            id="gw-1", name="oauth-authcode-gw", url="http://example.com",
            enabled=True, reachable=True, transport="sse",
            auth_type="oauth", auth_value=None,
            auth_query_params=None, ca_certificate=None,
            ca_certificate_sig=None,
            oauth_config={"grant_type": "authorization_code"},
            last_refresh_at=None, refresh_interval_seconds=None,
        )
        mock_client = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", lambda **kw: mock_ctx)
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            enable_ed25519_signing=False, health_check_timeout=5,
            auto_refresh_servers=False, httpx_admin_read_timeout=5,
            mcp_session_pool_enabled=False,
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))
        gateway_service._handle_gateway_failure = AsyncMock()

        await gateway_service._check_single_gateway_health(gw, user_email=None)
        gateway_service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_query_param_auth(self, gateway_service, monkeypatch):
        """Test health check with query_param auth decryption."""
        gw = _make_gateway(
            id="gw-1", name="qp-gw", url="http://example.com",
            enabled=True, reachable=True, transport="sse",
            auth_type="query_param", auth_value=None,
            auth_query_params={"api_key": "encrypted_val"},
            ca_certificate=None, ca_certificate_sig=None, oauth_config=None,
            last_refresh_at=None, refresh_interval_seconds=None,
        )

        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", lambda x: {"api_key": "secret"})
        monkeypatch.setattr("mcpgateway.services.gateway_service.apply_query_param_auth", lambda url, params: url + "?api_key=secret")
        monkeypatch.setattr("mcpgateway.services.gateway_service.sanitize_url_for_logging", lambda url, params: "http://example.com?api_key=***")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_stream_response = AsyncMock()
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream_response)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", lambda **kw: mock_ctx)
        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock())
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            enable_ed25519_signing=False, health_check_timeout=5,
            auto_refresh_servers=False, httpx_admin_read_timeout=5,
            mcp_session_pool_enabled=False,
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        await gateway_service._check_single_gateway_health(gw)


# ---------------------------------------------------------------------------
# list_gateways_for_user tests
# ---------------------------------------------------------------------------


class TestListGatewaysForUser:
    @pytest.mark.asyncio
    async def test_list_for_user_no_team(self, gateway_service, mock_gateway, monkeypatch):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [mock_gateway]
        db.commit = MagicMock()
        mock_team_svc = MagicMock()
        mock_team_svc.return_value.get_user_teams = AsyncMock(return_value=[])
        monkeypatch.setattr("mcpgateway.services.gateway_service.TeamManagementService", mock_team_svc)

        result = await gateway_service.list_gateways_for_user(db, "user@example.com")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_for_user_with_team_no_access(self, gateway_service, monkeypatch):
        db = MagicMock()
        mock_team_svc = MagicMock()
        mock_team_svc.return_value.get_user_teams = AsyncMock(return_value=[])
        monkeypatch.setattr("mcpgateway.services.gateway_service.TeamManagementService", mock_team_svc)

        result = await gateway_service.list_gateways_for_user(db, "user@example.com", team_id="team-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_for_user_with_team_access(self, gateway_service, mock_gateway, monkeypatch):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [mock_gateway]
        db.commit = MagicMock()
        team = SimpleNamespace(id="team-1", name="Team 1")
        mock_team_svc = MagicMock()
        mock_team_svc.return_value.get_user_teams = AsyncMock(return_value=[team])
        monkeypatch.setattr("mcpgateway.services.gateway_service.TeamManagementService", mock_team_svc)

        result = await gateway_service.list_gateways_for_user(db, "user@example.com", team_id="team-1")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_for_user_with_visibility_filter(self, gateway_service, mock_gateway, monkeypatch):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [mock_gateway]
        db.commit = MagicMock()
        mock_team_svc = MagicMock()
        mock_team_svc.return_value.get_user_teams = AsyncMock(return_value=[])
        monkeypatch.setattr("mcpgateway.services.gateway_service.TeamManagementService", mock_team_svc)

        result = await gateway_service.list_gateways_for_user(db, "user@example.com", visibility="public")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_for_user_include_inactive(self, gateway_service, mock_gateway, monkeypatch):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [mock_gateway]
        db.commit = MagicMock()
        mock_team_svc = MagicMock()
        mock_team_svc.return_value.get_user_teams = AsyncMock(return_value=[])
        monkeypatch.setattr("mcpgateway.services.gateway_service.TeamManagementService", mock_team_svc)

        result = await gateway_service.list_gateways_for_user(db, "user@example.com", include_inactive=True)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# create_ssl_context test
# ---------------------------------------------------------------------------


class TestCreateSslContext:
    def test_create_ssl_context_delegates_to_cache(self, gateway_service, monkeypatch):
        """Test SSL context creation delegates to get_cached_ssl_context."""
        sentinel = MagicMock()
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_cached_ssl_context", lambda cert: sentinel)
        result = gateway_service.create_ssl_context("FAKE_PEM")
        assert result is sentinel

    def test_create_ssl_context_passes_cert_through(self, gateway_service, monkeypatch):
        """Test SSL context creation passes the certificate to the cache function."""
        captured = {}
        def fake_cache(cert):
            captured["cert"] = cert
            return MagicMock()
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_cached_ssl_context", fake_cache)
        gateway_service.create_ssl_context("MY_CERT_DATA")
        assert captured["cert"] == "MY_CERT_DATA"


# ---------------------------------------------------------------------------
# _initialize_gateway tests
# ---------------------------------------------------------------------------


class TestInitializeGateway:

    @pytest.mark.asyncio
    async def test_oauth_auth_code_skips_connection(self, gateway_service):
        """OAuth authorization_code without flag returns empty."""
        caps, tools, resources, prompts = await gateway_service._initialize_gateway(
            url="http://example.com",
            auth_type="oauth",
            oauth_config={"grant_type": "authorization_code"},
            oauth_auto_fetch_tool_flag=False,
        )
        assert caps == {}
        assert tools == []
        assert resources == []
        assert prompts == []

    @pytest.mark.asyncio
    async def test_oauth_client_credentials_success(self, gateway_service):
        gateway_service.oauth_manager = AsyncMock()
        gateway_service.oauth_manager.get_access_token = AsyncMock(return_value="access-tok")
        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {"listChanged": True}}, [], [], [])
        )
        caps, tools, resources, prompts = await gateway_service._initialize_gateway(
            url="http://example.com",
            auth_type="oauth",
            oauth_config={"grant_type": "client_credentials"},
            transport="SSE",
        )
        assert "tools" in caps
        gateway_service.oauth_manager.get_access_token.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_oauth_client_credentials_token_failure(self, gateway_service):
        gateway_service.oauth_manager = AsyncMock()
        gateway_service.oauth_manager.get_access_token = AsyncMock(side_effect=Exception("expired"))
        with pytest.raises(GatewayConnectionError, match="OAuth authentication failed"):
            await gateway_service._initialize_gateway(
                url="http://example.com",
                auth_type="oauth",
                oauth_config={"grant_type": "client_credentials"},
            )

    @pytest.mark.asyncio
    async def test_sse_transport(self, gateway_service):
        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {}}, [SimpleNamespace(name="t1")], [], [])
        )
        caps, tools, resources, prompts = await gateway_service._initialize_gateway(
            url="http://example.com", transport="SSE"
        )
        assert len(tools) == 1
        gateway_service.connect_to_sse_server.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_streamablehttp_transport(self, gateway_service):
        gateway_service.connect_to_streamablehttp_server = AsyncMock(
            return_value=({"tools": {}}, [SimpleNamespace(name="t1")], [], [])
        )
        caps, tools, resources, prompts = await gateway_service._initialize_gateway(
            url="http://example.com", transport="StreamableHTTP"
        )
        assert len(tools) == 1
        gateway_service.connect_to_streamablehttp_server.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pre_auth_headers_used(self, gateway_service):
        gateway_service.connect_to_sse_server = AsyncMock(return_value=({}, [], [], []))
        await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication={"old": "header"},
            pre_auth_headers={"Authorization": "Bearer pre-auth"},
            transport="SSE",
        )
        call_args = gateway_service.connect_to_sse_server.call_args
        # The second positional arg is authentication
        assert call_args[0][1] == {"Authorization": "Bearer pre-auth"}

    @pytest.mark.asyncio
    async def test_string_auth_decoded(self, gateway_service, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", lambda x: {"Authorization": "decoded"})
        gateway_service.connect_to_sse_server = AsyncMock(return_value=({}, [], [], []))
        await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication="encoded_string",
            auth_type="bearer",
            transport="SSE",
        )
        call_args = gateway_service.connect_to_sse_server.call_args
        assert call_args[0][1] == {"Authorization": "decoded"}

    @pytest.mark.asyncio
    async def test_connection_failure_raises_gateway_error(self, gateway_service, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.gateway_service.sanitize_url_for_logging", lambda url, params=None: url)
        monkeypatch.setattr("mcpgateway.services.gateway_service.sanitize_exception_message", lambda msg, params=None: msg)
        gateway_service.connect_to_sse_server = AsyncMock(side_effect=ConnectionError("refused"))
        with pytest.raises(GatewayConnectionError, match="Failed to initialize gateway"):
            await gateway_service._initialize_gateway(url="http://example.com", transport="SSE")

    @pytest.mark.asyncio
    async def test_none_authentication_defaults_to_empty_dict(self, gateway_service):
        gateway_service.connect_to_sse_server = AsyncMock(return_value=({}, [], [], []))
        await gateway_service._initialize_gateway(
            url="http://example.com", authentication=None, transport="SSE"
        )
        call_args = gateway_service.connect_to_sse_server.call_args
        assert call_args[0][1] == {}

    @pytest.mark.asyncio
    async def test_oauth_auth_code_with_flag(self, gateway_service):
        """With oauth_auto_fetch_tool_flag=True, auth code gateway connects."""
        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {}}, [SimpleNamespace(name="t1")], [], [])
        )
        caps, tools, _, _ = await gateway_service._initialize_gateway(
            url="http://example.com",
            auth_type="oauth",
            oauth_config={"grant_type": "authorization_code"},
            oauth_auto_fetch_tool_flag=True,
            transport="SSE",
        )
        assert len(tools) == 1


# ---------------------------------------------------------------------------
# _refresh_gateway_tools_resources_prompts tests
# ---------------------------------------------------------------------------


class TestRefreshGatewayToolsResourcesPrompts:

    @pytest.mark.asyncio
    async def test_disabled_gateway_returns_empty(self, gateway_service):
        gw = SimpleNamespace(
            enabled=False, reachable=True, name="disabled-gw",
        )
        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-1", gateway=gw)
        assert result["tools_added"] == 0
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unreachable_gateway_returns_empty(self, gateway_service):
        gw = SimpleNamespace(
            enabled=True, reachable=False, name="unreachable-gw",
        )
        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-1", gateway=gw)
        assert result["tools_added"] == 0

    @pytest.mark.asyncio
    async def test_init_failure_returns_error(self, gateway_service):
        gw = SimpleNamespace(
            enabled=True, reachable=True, name="fail-gw",
            url="http://example.com", transport="sse",
            auth_type=None, auth_value=None, oauth_config=None,
            ca_certificate=None, auth_query_params=None,
        )
        gateway_service._initialize_gateway = AsyncMock(side_effect=Exception("connection refused"))
        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-1", gateway=gw)
        assert result["success"] is False
        assert "connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_auth_code_empty_response_returns_early(self, gateway_service):
        gw = SimpleNamespace(
            enabled=True, reachable=True, name="authcode-gw",
            url="http://example.com", transport="sse",
            auth_type="oauth", auth_value=None,
            oauth_config={"grant_type": "authorization_code"},
            ca_certificate=None, auth_query_params=None,
        )
        gateway_service._initialize_gateway = AsyncMock(return_value=({}, [], [], []))
        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-1", gateway=gw)
        assert result["tools_added"] == 0
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_no_gateway_obj_fetches_from_db(self, gateway_service, monkeypatch):
        """When gateway=None, fetches from DB using fresh_db_session."""
        mock_gw = MagicMock()
        mock_gw.enabled = True
        mock_gw.reachable = True
        mock_gw.name = "db-gw"
        mock_gw.url = "http://example.com"
        mock_gw.transport = "sse"
        mock_gw.auth_type = None
        mock_gw.auth_value = None
        mock_gw.oauth_config = None
        mock_gw.ca_certificate = None
        mock_gw.auth_query_params = None

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gw

        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_db), __exit__=MagicMock(return_value=False))
        ))
        gateway_service._initialize_gateway = AsyncMock(side_effect=Exception("fail"))

        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_no_gateway_obj_not_found(self, gateway_service, monkeypatch):
        """When gateway=None and not found in DB, returns empty result."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_db), __exit__=MagicMock(return_value=False))
        ))

        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-missing")
        assert result["tools_added"] == 0
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_query_param_auth_decryption(self, gateway_service, monkeypatch):
        """Test query param auth is decrypted for refresh."""
        gw = SimpleNamespace(
            enabled=True, reachable=True, name="qp-gw",
            url="http://example.com", transport="sse",
            auth_type="query_param", auth_value=None,
            oauth_config=None, ca_certificate=None,
            auth_query_params={"key": "encrypted_val"},
        )
        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", lambda x: {"key": "secret"})
        monkeypatch.setattr("mcpgateway.services.gateway_service.apply_query_param_auth", lambda url, params: url + "?key=secret")
        gateway_service._initialize_gateway = AsyncMock(side_effect=Exception("fail"))
        result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-1", gateway=gw)
        assert result["success"] is False
        # Verify init was called with the decrypted URL
        call_args = gateway_service._initialize_gateway.call_args
        assert "secret" in call_args.kwargs.get("url", call_args[1].get("url", ""))


# ---------------------------------------------------------------------------
# get_first_gateway_by_url tests
# ---------------------------------------------------------------------------


class TestGetFirstGatewayByUrl:
    def test_found(self, gateway_service, mock_gateway):
        db = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = mock_gateway
        db.execute.return_value.scalars.return_value = scalars_mock
        result = gateway_service.get_first_gateway_by_url(db, "http://example.com")
        assert result is not None

    def test_not_found(self, gateway_service):
        db = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = None
        db.execute.return_value.scalars.return_value = scalars_mock
        result = gateway_service.get_first_gateway_by_url(db, "http://missing.com")
        assert result is None


# ---------------------------------------------------------------------------
# _get_gateways tests
# ---------------------------------------------------------------------------


class TestGetGateways:
    def test_get_all_gateways(self, gateway_service, monkeypatch):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
        monkeypatch.setattr("mcpgateway.services.gateway_service.SessionLocal", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_db), __exit__=MagicMock(return_value=False))
        ))
        result = gateway_service._get_gateways(include_inactive=True)
        assert len(result) == 1

    def test_get_active_only(self, gateway_service, monkeypatch):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        monkeypatch.setattr("mcpgateway.services.gateway_service.SessionLocal", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_db), __exit__=MagicMock(return_value=False))
        ))
        result = gateway_service._get_gateways(include_inactive=False)
        assert result == []


# ---------------------------------------------------------------------------
# list_gateways token_teams filtering tests
# ---------------------------------------------------------------------------


class TestListGatewaysTokenTeams:
    """Cover token_teams-based access control filtering in list_gateways."""

    @pytest.mark.asyncio
    async def test_empty_token_teams_public_only(self, gateway_service, monkeypatch):
        """Empty token_teams means public-only access."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        gw = MagicMock(spec=DbGateway)
        gw.id = 1
        gw.visibility = "public"

        # Mock unified_paginate to return cursor-based result
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value=([gw], None)),
        )

        result, cursor = await gateway_service.list_gateways(db, token_teams=[])
        assert len(result) == 1
        assert cursor is None

    @pytest.mark.asyncio
    async def test_empty_token_teams_cache_set_called_when_results_support_model_dump(self, gateway_service, monkeypatch):
        """Public-only cache miss should populate cache when result objects support model_dump()."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        gw = MagicMock(spec=DbGateway)
        gw.id = 1
        gw.visibility = "public"

        # Return a gateway record and ensure converter returns an object with model_dump()
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value=([gw], None)),
        )
        gateway_service.convert_gateway_to_read = MagicMock(return_value=SimpleNamespace(model_dump=lambda **_kw: {"id": 1}))

        result, cursor = await gateway_service.list_gateways(db, token_teams=[])
        assert len(result) == 1
        assert cursor is None
        mock_cache.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scoped_token_teams(self, gateway_service, monkeypatch):
        """Team-scoped token returns team + public gateways."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        gw = MagicMock(spec=DbGateway)
        gw.id = 2
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value=([gw], None)),
        )

        result, cursor = await gateway_service.list_gateways(
            db, token_teams=["team-a"], user_email="user@test.com"
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_scoped_token_teams_with_visibility_filter(self, gateway_service, monkeypatch):
        """Token teams + visibility filter."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value=([], None)),
        )

        result, cursor = await gateway_service.list_gateways(
            db, token_teams=["team-a"], visibility="team"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_scoped_token_owner_clause_is_private_only(self, gateway_service, monkeypatch):
        """Scoped tokens must not use owner_email as a blanket bypass for non-private visibility."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        mock_paginate = AsyncMock(return_value=([], None))
        monkeypatch.setattr("mcpgateway.services.gateway_service.unified_paginate", mock_paginate)

        await gateway_service.list_gateways(
            db,
            token_teams=["team-a"],
            user_email="user@test.com",
        )

        query_arg = mock_paginate.await_args.kwargs["query"]
        compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
        assert "gateways.owner_email = 'user@test.com' AND gateways.visibility = 'private'" in compiled

    @pytest.mark.asyncio
    async def test_user_email_team_access_no_token_teams(self, gateway_service, monkeypatch):
        """User-based team access when token_teams not set."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        # Mock TeamManagementService
        mock_team_svc = MagicMock()
        mock_team_svc.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="t1")])
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.TeamManagementService",
            MagicMock(return_value=mock_team_svc),
        )
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value=([], None)),
        )

        result, cursor = await gateway_service.list_gateways(
            db, user_email="user@test.com"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_user_email_specific_team_no_access(self, gateway_service, monkeypatch):
        """User requesting specific team they don't belong to returns empty."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        mock_team_svc = MagicMock()
        mock_team_svc.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="t1")])
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.TeamManagementService",
            MagicMock(return_value=mock_team_svc),
        )

        result = await gateway_service.list_gateways(
            db, user_email="user@test.com", team_id="t-other"
        )
        assert result == ([], None)

    @pytest.mark.asyncio
    async def test_user_email_specific_team_with_access_and_visibility_filter(self, gateway_service, monkeypatch):
        """User requesting a team they belong to should build access conditions (team_id branch)."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        mock_team_svc = MagicMock()
        mock_team_svc.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="team-1")])
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.TeamManagementService",
            MagicMock(return_value=mock_team_svc),
        )
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value=([], None)),
        )

        result, cursor = await gateway_service.list_gateways(
            db,
            user_email="user@test.com",
            team_id="team-1",
            visibility="team",
        )
        assert result == []
        assert cursor is None

    @pytest.mark.asyncio
    async def test_page_based_pagination(self, gateway_service, monkeypatch):
        """Page-based pagination returns dict format."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        gw = MagicMock(spec=DbGateway)
        gw.id = 1
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value={"data": [gw], "pagination": {"page": 1}, "links": {}}),
        )

        result = await gateway_service.list_gateways(db, page=1)
        assert isinstance(result, dict)
        assert "data" in result
        assert "pagination" in result

    @pytest.mark.asyncio
    async def test_convert_gateway_validation_error(self, gateway_service, monkeypatch):
        """Validation errors during conversion are logged and skipped."""
        db = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        bad_gw = MagicMock(spec=DbGateway)
        bad_gw.id = 99
        bad_gw.name = "bad"
        # Make convert_gateway_to_read raise for this gateway
        original_convert = gateway_service.convert_gateway_to_read
        gateway_service.convert_gateway_to_read = MagicMock(side_effect=ValueError("bad data"))

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.unified_paginate",
            AsyncMock(return_value=([bad_gw], None)),
        )

        result, cursor = await gateway_service.list_gateways(db)
        assert result == []  # Bad gateway skipped

    @pytest.mark.asyncio
    async def test_cache_hit(self, gateway_service, monkeypatch):
        """Cached result returned for public-only queries."""
        db = MagicMock()
        mock_cache = MagicMock()
        cached_gw = MagicMock()
        cached_gw.model_dump = MagicMock(return_value={"id": 1})
        mock_cache.get = AsyncMock(return_value={"gateways": [{"id": 1}], "next_cursor": None})
        mock_cache.hash_filters = MagicMock(return_value="h")
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: mock_cache)

        result, cursor = await gateway_service.list_gateways(db, token_teams=[])
        assert len(result) == 1
        assert cursor is None


# ---------------------------------------------------------------------------
# update_gateway advanced paths
# ---------------------------------------------------------------------------


class TestUpdateGatewayAdvanced:
    """Cover query_param auth, passthrough_headers, stale cleanup in update_gateway."""

    @pytest.mark.asyncio
    async def test_update_passthrough_headers_list(self, gateway_service, mock_gateway, monkeypatch):
        """Passthrough headers as list are set directly."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = None
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            passthrough_headers=["X-Custom", "X-Other"],
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        assert mock_gateway.passthrough_headers == ["X-Custom", "X-Other"]

    @pytest.mark.asyncio
    async def test_update_passthrough_headers_string(self, gateway_service, mock_gateway, monkeypatch):
        """Passthrough headers as comma-separated string are parsed."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = None
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            passthrough_headers="X-Custom, X-Other",
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        assert mock_gateway.passthrough_headers == ["X-Custom", "X-Other"]

    @pytest.mark.asyncio
    async def test_update_passthrough_headers_invalid_type(self, gateway_service, mock_gateway, monkeypatch):
        """Invalid passthrough_headers type raises GatewayError."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = None
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            passthrough_headers=12345,  # invalid type
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        with pytest.raises(GatewayError, match="Invalid passthrough_headers"):
            await gateway_service.update_gateway(db, mock_gateway.id, update_data)

    @pytest.mark.asyncio
    async def test_update_auth_headers_multiple(self, gateway_service, mock_gateway, monkeypatch):
        """Multiple custom auth headers update replaces auth_value."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = None
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
        )
        update_data.auth_token = "*****"  # Masked value skips the elif auth_value override
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None
        update_data.auth_headers = [{"key": "X-Api-Key", "value": "secret123"}]
        update_data.visibility = None
        update_data.oauth_config = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        # auth_value gets encoded by _prepare_gateway_for_read; verify it's a non-empty encoded string
        assert isinstance(mock_gateway.auth_value, str) and len(mock_gateway.auth_value) > 0

    @pytest.mark.asyncio
    async def test_update_stale_tools_cleaned_up(self, gateway_service, mock_gateway, monkeypatch):
        """Stale tools/resources/prompts are deleted during update."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = None
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        # Gateway has a stale tool that won't be in the new tools
        stale_tool = MagicMock(spec=DbTool)
        stale_tool.id = 999
        stale_tool.original_name = "old_tool"
        mock_gateway.tools = [stale_tool]
        mock_gateway.resources = []
        mock_gateway.prompts = []

        update_data = _make_gateway(
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        # _initialize_gateway returns a new tool with different name
        new_tool = SimpleNamespace(name="new_tool", description="new", inputSchema={"type": "object"})
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(
            return_value=({"tools": {}}, [new_tool], [], [])
        ))
        monkeypatch.setattr(gateway_service, "_create_db_tool", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        # Verify that db.execute was called (for bulk deletes)
        assert db.execute.call_count > 1  # initial fetch + delete calls

    @pytest.mark.asyncio
    async def test_update_oauth_config(self, gateway_service, mock_gateway, monkeypatch):
        """OAuth config updates set the config on the gateway."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = "oauth"
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []
        mock_gateway.oauth_config = None

        update_data = _make_gateway(
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config={"client_id": "cid", "grant_type": "client_credentials"},
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        assert mock_gateway.oauth_config == {"client_id": "cid", "grant_type": "client_credentials"}

    @pytest.mark.asyncio
    async def test_update_metadata_fields(self, gateway_service, mock_gateway, monkeypatch):
        """Modified_by and other metadata are set during update."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = None
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(
            db, mock_gateway.id, update_data,
            modified_by="admin@test.com",
            modified_from_ip="1.2.3.4",
            modified_via="api",
            modified_user_agent="test-agent/1.0",
        )
        assert mock_gateway.modified_by == "admin@test.com"
        assert mock_gateway.modified_from_ip == "1.2.3.4"
        assert mock_gateway.modified_via == "api"
        assert mock_gateway.modified_user_agent == "test-agent/1.0"
        assert mock_gateway.version == 2

    @pytest.mark.asyncio
    async def test_update_init_failure_continues(self, gateway_service, mock_gateway, monkeypatch):
        """Initialization failure during update is logged but doesn't block update."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = None
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = None  # Test version=None path
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type=None,
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(side_effect=Exception("connection failed")))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        # Update proceeds even if init fails
        assert mock_gateway.version == 1  # version set to 1 when was None

    @pytest.mark.asyncio
    async def test_update_clear_auth_type(self, gateway_service, mock_gateway, monkeypatch):
        """Clearing auth_type also clears auth_value."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = {"Authorization": "Bearer token123"}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type="",  # Clear auth
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        assert mock_gateway.auth_type == ""
        assert mock_gateway.auth_value == ""

    @pytest.mark.asyncio
    async def test_update_switch_away_from_queryparam(self, gateway_service, mock_gateway, monkeypatch):
        """Switching away from query_param clears auth_query_params."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = "query_param"
        mock_gateway.auth_value = None
        mock_gateway.auth_query_params = {"key": "encrypted_val"}
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type="bearer",  # Switch from query_param to bearer
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        assert mock_gateway.auth_query_params is None
        assert mock_gateway.auth_type == "bearer"


# ---------------------------------------------------------------------------
# _check_single_gateway_health - OAuth auth_code and session pool paths
# ---------------------------------------------------------------------------


class TestCheckSingleHealthAuthCode:
    """Cover auth_code token lookup and session pool paths in health checks."""

    @pytest.mark.asyncio
    async def test_auth_code_no_user_email(self, gateway_service, monkeypatch):
        """Auth code health check without user email calls failure handler."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.url = "http://gw.test"
        gw.auth_type = "oauth"
        gw.oauth_config = {"grant_type": "authorization_code"}
        gw.enabled = True
        gw.reachable = True
        gw.transport = "sse"
        gw.auth_value = None
        gw.auth_query_params = None
        gw.ca_certificate = None

        gateway_service._handle_gateway_failure = AsyncMock()
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        await gateway_service._check_single_gateway_health(gw, user_email=None)
        gateway_service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_code_token_found(self, gateway_service, monkeypatch):
        """Auth code health check with valid token makes request."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.url = "http://gw.test"
        gw.auth_type = "oauth"
        gw.oauth_config = {"grant_type": "authorization_code"}
        gw.enabled = True
        gw.reachable = True
        gw.transport = "sse"
        gw.auth_value = None
        gw.auth_query_params = None
        gw.ca_certificate = None

        mock_token_svc = MagicMock()
        mock_token_svc.get_user_token = AsyncMock(return_value="access_tok")
        monkeypatch.setattr(
            "mcpgateway.services.token_storage_service.TokenStorageService",
            MagicMock(return_value=mock_token_svc),
        )
        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        client_mock = AsyncMock()
        client_mock.stream = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", MagicMock(
            return_value=MagicMock(__aenter__=AsyncMock(return_value=client_mock), __aexit__=AsyncMock(return_value=False))
        ))

        await gateway_service._check_single_gateway_health(gw, user_email="user@test.com")

    @pytest.mark.asyncio
    async def test_auth_code_no_token_calls_failure(self, gateway_service, monkeypatch):
        """Auth code health check without stored token calls failure handler."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.url = "http://gw.test"
        gw.auth_type = "oauth"
        gw.oauth_config = {"grant_type": "authorization_code"}
        gw.enabled = True
        gw.reachable = True
        gw.transport = "sse"
        gw.auth_value = None
        gw.auth_query_params = None
        gw.ca_certificate = None

        mock_token_svc = MagicMock()
        mock_token_svc.get_user_token = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "mcpgateway.services.token_storage_service.TokenStorageService",
            MagicMock(return_value=mock_token_svc),
        )
        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        gateway_service._handle_gateway_failure = AsyncMock()
        await gateway_service._check_single_gateway_health(gw, user_email="user@test.com")
        gateway_service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_code_token_exception(self, gateway_service, monkeypatch):
        """Auth code health check with token exception calls failure handler."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.url = "http://gw.test"
        gw.auth_type = "oauth"
        gw.oauth_config = {"grant_type": "authorization_code"}
        gw.enabled = True
        gw.reachable = True
        gw.transport = "sse"
        gw.auth_value = None
        gw.auth_query_params = None
        gw.ca_certificate = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(side_effect=Exception("DB error")), __exit__=MagicMock(return_value=False))
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        gateway_service._handle_gateway_failure = AsyncMock()
        await gateway_service._check_single_gateway_health(gw, user_email="user@test.com")
        gateway_service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_client_creds_health_exception(self, gateway_service, monkeypatch):
        """Client creds flow token failure calls failure handler."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.url = "http://gw.test"
        gw.auth_type = "oauth"
        gw.oauth_config = {"grant_type": "client_credentials"}
        gw.enabled = True
        gw.reachable = True
        gw.transport = "sse"
        gw.auth_value = None
        gw.auth_query_params = None
        gw.ca_certificate = None

        gateway_service.oauth_manager = MagicMock()
        gateway_service.oauth_manager.get_access_token = AsyncMock(side_effect=Exception("token error"))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        gateway_service._handle_gateway_failure = AsyncMock()
        await gateway_service._check_single_gateway_health(gw, user_email=None)
        gateway_service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_string_auth_decode(self, gateway_service, monkeypatch):
        """Health check with string auth_value decodes it."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.url = "http://gw.test"
        gw.auth_type = "bearer"
        gw.oauth_config = None
        gw.enabled = True
        gw.reachable = True
        gw.transport = "sse"
        gw.auth_value = "encoded_string"
        gw.auth_query_params = None
        gw.ca_certificate = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", MagicMock(return_value={"Authorization": "Bearer tok"}))
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        client_mock = AsyncMock()
        client_mock.stream = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", MagicMock(
            return_value=MagicMock(__aenter__=AsyncMock(return_value=client_mock), __aexit__=AsyncMock(return_value=False))
        ))

        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(
                execute=MagicMock(return_value=_make_execute_result(scalar=gw))
            )), __exit__=MagicMock(return_value=False))
        ))

        await gateway_service._check_single_gateway_health(gw)

    @pytest.mark.asyncio
    async def test_reactivate_unreachable_gateway(self, gateway_service, monkeypatch):
        """Passing health check reactivates previously unreachable gateway."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.url = "http://gw.test"
        gw.auth_type = None
        gw.oauth_config = None
        gw.enabled = True
        gw.reachable = False  # Previously unreachable
        gw.transport = "sse"
        gw.auth_value = {}
        gw.auth_query_params = None
        gw.ca_certificate = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        client_mock = AsyncMock()
        client_mock.stream = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", MagicMock(
            return_value=MagicMock(__aenter__=AsyncMock(return_value=client_mock), __aexit__=AsyncMock(return_value=False))
        ))

        # Mock SessionLocal and set_gateway_state for reactivation
        mock_db = MagicMock()
        monkeypatch.setattr("mcpgateway.services.gateway_service.SessionLocal", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_db), __exit__=MagicMock(return_value=False))
        ))
        gateway_service.set_gateway_state = AsyncMock()

        monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(
                execute=MagicMock(return_value=_make_execute_result(scalar=gw))
            )), __exit__=MagicMock(return_value=False))
        ))

        await gateway_service._check_single_gateway_health(gw)
        gateway_service.set_gateway_state.assert_awaited_once()


# ---------------------------------------------------------------------------
# _handle_gateway_failure advanced cases
# ---------------------------------------------------------------------------


class TestHandleGatewayFailureAdvanced:
    """Cover threshold-reaching and disabled paths."""

    @pytest.mark.asyncio
    async def test_failure_threshold_disabled(self, gateway_service, monkeypatch):
        """GW_FAILURE_THRESHOLD == -1 means no action taken."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.GW_FAILURE_THRESHOLD", -1)
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.enabled = True
        gw.reachable = True
        await gateway_service._handle_gateway_failure(gw)
        # No exception, no side effects

    @pytest.mark.asyncio
    async def test_failure_disabled_gateway(self, gateway_service):
        """Disabled gateway is ignored."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.enabled = False
        gw.reachable = True
        await gateway_service._handle_gateway_failure(gw)

    @pytest.mark.asyncio
    async def test_failure_unreachable_gateway(self, gateway_service):
        """Already unreachable gateway is ignored."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.enabled = True
        gw.reachable = False
        await gateway_service._handle_gateway_failure(gw)


# ---------------------------------------------------------------------------
# check_health_of_gateways tests
# ---------------------------------------------------------------------------


class TestCheckHealthOfGateways:
    """Cover check_health_of_gateways batch processing."""

    @pytest.mark.asyncio
    async def test_empty_gateways_returns_true(self, gateway_service, monkeypatch):
        """Empty gateway list returns True immediately."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))
        result = await gateway_service.check_health_of_gateways([])
        assert result is True

    @pytest.mark.asyncio
    async def test_batch_skips_one_time_auth(self, gateway_service, monkeypatch):
        """Gateways with one_time_auth are skipped."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.auth_type = "one_time_auth"

        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        gateway_service._check_single_gateway_health = AsyncMock()
        result = await gateway_service.check_health_of_gateways([gw])
        assert result is True
        # Health check not called since all gateways were one_time_auth
        gateway_service._check_single_gateway_health.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_processes_normal_gateways(self, gateway_service, monkeypatch):
        """Normal gateways are processed in batch."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw1"
        gw.name = "test"
        gw.auth_type = "bearer"

        monkeypatch.setattr("mcpgateway.services.gateway_service.create_span", MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
        ))

        gateway_service._check_single_gateway_health = AsyncMock()
        result = await gateway_service.check_health_of_gateways([gw])
        assert result is True
        gateway_service._check_single_gateway_health.assert_awaited_once()


# ---------------------------------------------------------------------------
# set_gateway_state activation with stale cleanup
# ---------------------------------------------------------------------------


class TestSetGatewayStateActivation:
    """Cover activation path with tool/resource/prompt refresh and stale cleanup."""

    @pytest.mark.asyncio
    async def test_activate_with_stale_cleanup(self, gateway_service, mock_gateway, monkeypatch):
        """Activating gateway refreshes tools and cleans stale ones."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.enabled = False
        mock_gateway.reachable = False
        mock_gateway.auth_type = None
        mock_gateway.auth_query_params = None
        mock_gateway.oauth_config = None
        mock_gateway.version = 1

        # Stale tool that won't be in new discovery
        stale_tool = MagicMock(spec=DbTool)
        stale_tool.id = 999
        stale_tool.original_name = "old_tool"
        mock_gateway.tools = [stale_tool]
        mock_gateway.resources = []
        mock_gateway.prompts = []

        new_tool = SimpleNamespace(name="fresh_tool", description="d", inputSchema={"type": "object"})
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(
            return_value=({"tools": {}}, [new_tool], [], [])
        ))
        monkeypatch.setattr(gateway_service, "_create_db_tool", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())

        result = await gateway_service.set_gateway_state(db, mock_gateway.id, activate=True, reachable=True)
        assert mock_gateway.enabled is True
        assert mock_gateway.reachable is True
        # DB execute called for stale cleanup
        assert db.execute.call_count > 1

    @pytest.mark.asyncio
    async def test_activate_with_query_param_auth(self, gateway_service, mock_gateway, monkeypatch):
        """Activating gateway with query_param auth decrypts credentials."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.enabled = False
        mock_gateway.reachable = False
        mock_gateway.auth_type = "query_param"
        mock_gateway.auth_query_params = {"api_key": "encrypted_val"}
        mock_gateway.oauth_config = None
        mock_gateway.version = 1
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", MagicMock(return_value={"api_key": "raw_key"}))
        monkeypatch.setattr("mcpgateway.services.gateway_service.apply_query_param_auth", MagicMock(return_value="http://example.com?api_key=raw_key"))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(
            return_value=({"tools": {}}, [], [], [])
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())

        result = await gateway_service.set_gateway_state(db, mock_gateway.id, activate=True, reachable=True)
        assert mock_gateway.enabled is True

    @pytest.mark.asyncio
    async def test_activate_query_param_decrypt_failure(self, gateway_service, mock_gateway, monkeypatch):
        """Query param decryption failure is handled gracefully."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.enabled = False
        mock_gateway.reachable = False
        mock_gateway.auth_type = "query_param"
        mock_gateway.auth_query_params = {"api_key": "bad_encrypted"}
        mock_gateway.oauth_config = None
        mock_gateway.version = 1
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", MagicMock(side_effect=Exception("decrypt error")))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(
            return_value=({"tools": {}}, [], [], [])
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())

        result = await gateway_service.set_gateway_state(db, mock_gateway.id, activate=True, reachable=True)
        assert mock_gateway.enabled is True

    @pytest.mark.asyncio
    async def test_activate_with_new_resources_and_prompts(self, gateway_service, mock_gateway, monkeypatch):
        """Activating gateway adds new tools, resources, and prompts."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.enabled = False
        mock_gateway.reachable = False
        mock_gateway.auth_type = None
        mock_gateway.auth_query_params = None
        mock_gateway.oauth_config = None
        mock_gateway.version = 1
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        new_tool = SimpleNamespace(name="tool1", description="d", inputSchema={"type": "object"})
        new_resource = SimpleNamespace(uri="res://1", name="res1", description="d", mimeType="text/plain")
        new_prompt = SimpleNamespace(name="prompt1", description="d", arguments=[])
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(
            return_value=({"tools": {}, "resources": {}, "prompts": {}}, [new_tool], [new_resource], [new_prompt])
        ))
        monkeypatch.setattr(gateway_service, "_create_db_tool", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", MagicMock())

        result = await gateway_service.set_gateway_state(db, mock_gateway.id, activate=True, reachable=True)
        # Verify add_all was called for new items
        assert db.add_all.call_count >= 1

    @pytest.mark.asyncio
    async def test_activate_only_update_reachable(self, gateway_service, mock_gateway, monkeypatch):
        """only_update_reachable skips full re-initialization."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.enabled = True
        mock_gateway.reachable = False
        mock_gateway.auth_type = None
        mock_gateway.version = 1

        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))

        result = await gateway_service.set_gateway_state(
            db, mock_gateway.id, activate=True, reachable=True, only_update_reachable=True
        )
        assert mock_gateway.reachable is True


# ---------------------------------------------------------------------------
# update_gateway query_param auth
# ---------------------------------------------------------------------------


class TestUpdateGatewayQueryParam:
    """Cover query_param auth update paths."""

    @pytest.mark.asyncio
    async def test_switch_to_queryparam_disabled(self, gateway_service, mock_gateway, monkeypatch):
        """Switching to query_param auth when disabled raises ValueError."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type="query_param",
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = "api_key"
        update_data.auth_query_param_value = "secret"

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            insecure_allow_queryparam_auth=False,
            masked_auth_value="*****",
        ))

        with pytest.raises(GatewayError, match="Query parameter authentication is disabled"):
            await gateway_service.update_gateway(db, mock_gateway.id, update_data)

    @pytest.mark.asyncio
    async def test_switch_to_queryparam_host_not_allowed(self, gateway_service, mock_gateway, monkeypatch):
        """Query param auth with host not in allowlist raises ValueError."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type="query_param",
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = None
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = "api_key"
        update_data.auth_query_param_value = "secret"

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            insecure_allow_queryparam_auth=True,
            insecure_queryparam_auth_allowed_hosts=["allowed.host.com"],
            masked_auth_value="*****",
        ))

        with pytest.raises(GatewayError, match="not in the allowed hosts"):
            await gateway_service.update_gateway(db, mock_gateway.id, update_data)

    @pytest.mark.asyncio
    async def test_switch_to_queryparam_success(self, gateway_service, mock_gateway, monkeypatch):
        """Successfully switching to query_param auth encrypts and stores."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = {}
        mock_gateway.auth_query_params = None
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type="query_param",
            auth_value=None,
            url="http://example.com/gateway",
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = "*****"
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = "api_key"
        update_data.auth_query_param_value = "my_secret_key"

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings", MagicMock(
            insecure_allow_queryparam_auth=True,
            insecure_queryparam_auth_allowed_hosts=None,
            masked_auth_value="*****",
            health_check_timeout=10,
            httpx_admin_read_timeout=5,
        ))
        monkeypatch.setattr("mcpgateway.services.gateway_service.encode_auth", MagicMock(return_value="encrypted_val"))
        monkeypatch.setattr("mcpgateway.services.gateway_service.apply_query_param_auth", MagicMock(return_value="http://example.com?api_key=my_secret_key"))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        assert mock_gateway.auth_type == "query_param"
        assert mock_gateway.auth_query_params is not None

    @pytest.mark.asyncio
    async def test_existing_queryparam_decrypt_on_update(self, gateway_service, mock_gateway, monkeypatch):
        """Existing query_param gateway decrypts on URL change."""
        db = MagicMock()
        db.execute.return_value = _make_execute_result(scalar=mock_gateway)
        mock_gateway.auth_type = "query_param"
        mock_gateway.auth_value = None
        mock_gateway.auth_query_params = {"api_key": "encrypted_val"}
        mock_gateway.version = 1
        mock_gateway.tags = []

        update_data = _make_gateway(
            auth_type=None,
            auth_value=None,
            url="http://new-example.com/gateway",  # URL changed
            passthrough_headers=None,
            visibility=None,
            oauth_config=None,
        )
        update_data.auth_token = "*****"
        update_data.auth_password = None
        update_data.auth_header_value = None
        update_data.auth_query_param_key = None
        update_data.auth_query_param_value = None

        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[mock_gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service.decode_auth", MagicMock(return_value={"api_key": "decrypted_val"}))
        monkeypatch.setattr("mcpgateway.services.gateway_service.apply_query_param_auth", MagicMock(return_value="http://new-example.com?api_key=decrypted_val"))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(return_value=({"tools": {}}, [], [], [])))

        result = await gateway_service.update_gateway(db, mock_gateway.id, update_data)
        assert result is not None


# ---------------------------------------------------------------------------
# _run_health_checks
# ---------------------------------------------------------------------------


class TestRunLeaderHeartbeat:
    """Cover _run_leader_heartbeat loop."""

    @pytest.mark.asyncio
    async def test_heartbeat_no_redis(self, gateway_service):
        """Heartbeat exits when no redis client."""
        gateway_service._instance_id = "test-id"
        gateway_service._leader_key = "leader:health_check"
        gateway_service._leader_ttl = 30
        gateway_service._redis_client = None
        gateway_service._leader_heartbeat_interval = 0
        await gateway_service._run_leader_heartbeat()

    @pytest.mark.asyncio
    async def test_heartbeat_lost_leadership(self, gateway_service):
        """Heartbeat exits when leadership is lost."""
        gateway_service._instance_id = "test-id"
        gateway_service._leader_key = "leader:health_check"
        gateway_service._leader_ttl = 30
        gateway_service._redis_client = AsyncMock()
        gateway_service._redis_client.get = AsyncMock(return_value="other-leader")
        gateway_service._leader_heartbeat_interval = 0
        await gateway_service._run_leader_heartbeat()

    @pytest.mark.asyncio
    async def test_heartbeat_refreshes_ttl(self, gateway_service):
        """Heartbeat refreshes TTL then exits when losing leadership."""
        gateway_service._instance_id = "test-id"
        gateway_service._leader_key = "leader:health_check"
        gateway_service._leader_ttl = 30
        call_count = 0

        async def mock_get(*args):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return "test-id"
            return "other-leader"

        gateway_service._redis_client = AsyncMock()
        gateway_service._redis_client.get = mock_get
        gateway_service._redis_client.expire = AsyncMock()
        gateway_service._leader_heartbeat_interval = 0
        await gateway_service._run_leader_heartbeat()
        gateway_service._redis_client.expire.assert_awaited_once()


# ---------------------------------------------------------------------------
# direct_proxy feature flag guard tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_gateway_direct_proxy_rejected_when_disabled(gateway_service, monkeypatch):
    """register_gateway raises GatewayError when direct_proxy mode is used but the feature flag is off."""
    # Bypass slug-conflict check so we reach the feature-flag guard
    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_args, **_kwargs: None)

    gateway_data = GatewayCreate(
        name="Proxy Disabled Gateway",
        url="https://proxy-disabled.example.com",
        description="Should be rejected",
        transport="SSE",
        gateway_mode="direct_proxy",
    )

    mock_settings = MagicMock()
    mock_settings.mcpgateway_direct_proxy_enabled = False
    mock_settings.masked_auth_value = "***MASKED***"

    db = MagicMock()

    with patch("mcpgateway.services.gateway_service.settings", mock_settings):
        with pytest.raises(GatewayError, match="disabled"):
            await gateway_service.register_gateway(db, gateway_data)


@pytest.mark.asyncio
async def test_register_gateway_direct_proxy_allowed_when_enabled(gateway_service, monkeypatch):
    """register_gateway does NOT raise GatewayError for the feature flag when direct_proxy is enabled."""
    # Bypass slug-conflict check
    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_args, **_kwargs: None)

    gateway_data = GatewayCreate(
        name="Proxy Enabled Gateway",
        url="https://proxy-enabled.example.com",
        description="Should pass the feature flag check",
        transport="SSE",
        gateway_mode="direct_proxy",
    )

    mock_settings = MagicMock()
    mock_settings.mcpgateway_direct_proxy_enabled = True
    mock_settings.masked_auth_value = "***MASKED***"

    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    db.refresh = MagicMock()

    # Let the rest of the method proceed past the guard
    gateway_service._check_gateway_uniqueness = MagicMock(return_value=None)
    gateway_service._initialize_gateway = AsyncMock(return_value=({}, [], [], []))
    gateway_service._notify_gateway_added = AsyncMock()

    with patch("mcpgateway.services.gateway_service.settings", mock_settings):
        # Should NOT raise GatewayError for the feature-flag check.
        # It may raise other errors downstream; we only care that the
        # "disabled" guard did not fire.
        try:
            await gateway_service.register_gateway(db, gateway_data)
        except GatewayError as exc:
            assert "disabled" not in str(exc).lower(), f"Feature-flag guard should not fire when enabled, but got: {exc}"


@pytest.mark.asyncio
async def test_update_gateway_direct_proxy_rejected_when_disabled(gateway_service, monkeypatch):
    """update_gateway raises GatewayError when switching to direct_proxy with the feature flag off."""
    existing_gateway = MagicMock()
    existing_gateway.id = "gw-flag-test"
    existing_gateway.name = "Existing Cache Gateway"
    existing_gateway.url = "https://existing.example.com"
    existing_gateway.enabled = True
    existing_gateway.gateway_mode = "cache"
    existing_gateway.tools = []
    existing_gateway.resources = []
    existing_gateway.prompts = []
    existing_gateway.email_team = None

    # get_for_update returns the existing gateway (first call) and None (slug-check)
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.get_for_update",
        MagicMock(side_effect=[existing_gateway, None]),
    )
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service._get_registry_cache",
        lambda: MagicMock(invalidate_gateways=AsyncMock()),
    )
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service._get_tool_lookup_cache",
        lambda: MagicMock(invalidate_gateway=AsyncMock()),
    )
    monkeypatch.setattr(
        "mcpgateway.cache.admin_stats_cache.admin_stats_cache",
        MagicMock(invalidate_tags=AsyncMock()),
    )

    mock_settings = MagicMock()
    mock_settings.mcpgateway_direct_proxy_enabled = False
    mock_settings.masked_auth_value = "***MASKED***"

    update_data = GatewayUpdate(gateway_mode="direct_proxy")

    db = MagicMock()
    db.rollback = MagicMock()

    with patch("mcpgateway.services.gateway_service.settings", mock_settings):
        with pytest.raises(GatewayError, match="disabled"):
            await gateway_service.update_gateway(db, "gw-flag-test", update_data)
