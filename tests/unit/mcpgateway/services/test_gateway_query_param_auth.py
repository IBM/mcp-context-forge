# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_query_param_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for query parameter authentication in GatewayService.

Tests the query_param auth_type which appends decrypted API keys as URL
query parameters for upstream MCP servers that require this authentication
method (e.g., Tavily MCP server).

Security Note:
    Query parameter authentication is inherently insecure (CWE-598).
    These tests verify that:
    1. Auth params are properly encrypted at rest
    2. Auth params are properly decrypted only when making requests
    3. URLs with auth params are sanitized in logs
    4. The INSECURE_ALLOW_QUERY_PARAM_AUTH feature flag is respected
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest
from url_normalize import url_normalize

# First-Party
from mcpgateway.schemas import GatewayCreate, GatewayUpdate
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.url_auth import apply_query_param_auth, sanitize_url_for_logging


def _make_execute_result(*, scalar=None, scalars_list=None):
    """Return a MagicMock that behaves like SQLAlchemy Result object."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


@pytest.fixture
def gateway_service():
    """Create a GatewayService instance with mocked HTTP client."""
    service = GatewayService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def test_db():
    """Create a mock database session."""
    db = MagicMock()
    db.execute = Mock()
    db.add = Mock()
    db.flush = Mock()
    db.commit = Mock()
    db.refresh = Mock()
    db.rollback = Mock()
    return db


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes."""
    with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, \
         patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def _bypass_gatewayread_validation(monkeypatch):
    """Stub GatewayRead.model_validate to return input unchanged."""
    from mcpgateway.schemas import GatewayRead
    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: x))


@pytest.fixture(autouse=True)
def mock_all_settings():
    """Mock settings in both schemas and gateway_service modules."""
    with patch("mcpgateway.schemas.settings") as schema_settings, \
         patch("mcpgateway.services.gateway_service.settings") as service_settings:
        # Configure schema settings
        schema_settings.insecure_allow_queryparam_auth = True
        schema_settings.insecure_queryparam_auth_allowed_hosts = ["api.tavily.com", "mcp.tavily.com", "api.example.com"]
        schema_settings.masked_auth_value = "*****"

        # Configure service settings
        service_settings.insecure_allow_queryparam_auth = True
        service_settings.insecure_queryparam_auth_allowed_hosts = ["api.tavily.com", "mcp.tavily.com", "api.example.com"]
        service_settings.masked_auth_value = "*****"
        service_settings.cache_type = "none"

        yield {"schema": schema_settings, "service": service_settings}


class TestQueryParamAuthRegistration:
    """Tests for registering gateways with query_param authentication."""

    @pytest.mark.asyncio
    async def test_register_gateway_with_query_param_auth(self, gateway_service, test_db, monkeypatch):
        """Test registering a gateway with query_param auth encrypts the params."""
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # name-conflict check
                _make_execute_result(scalars_list=[]),  # tool lookup
            ]
        )
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

        url = url_normalize("https://api.tavily.com/mcp")
        gateway_service._initialize_gateway = AsyncMock(
            return_value=({"tools": {"listChanged": True}}, [], [], [])
        )
        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "tavily_gateway"
        mock_model.url = url
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(
            name="tavily_gateway",
            url=url,
            description="Tavily MCP server",
            auth_type="query_param",
            auth_query_param_key="tavilyApiKey",
            auth_query_param_value="secret-api-key-123",
        )

        await gateway_service.register_gateway(test_db, gateway_create)

        # Verify the gateway was added to the database
        test_db.add.assert_called_once()
        added_gateway = test_db.add.call_args[0][0]

        # Verify auth_type is set correctly
        assert added_gateway.auth_type == "query_param"

        # Verify auth_query_params is encrypted (stored as dict with encrypted values)
        assert added_gateway.auth_query_params is not None
        assert "tavilyApiKey" in added_gateway.auth_query_params

        # The value should be encrypted, not plaintext
        encrypted_value = added_gateway.auth_query_params["tavilyApiKey"]
        assert encrypted_value != "secret-api-key-123"

    @pytest.mark.asyncio
    async def test_register_gateway_query_param_initializes_with_auth(self, gateway_service, test_db, monkeypatch):
        """Test that _initialize_gateway receives decrypted auth params."""
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),
                _make_execute_result(scalars_list=[]),
            ]
        )
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[])))))

        url = url_normalize("https://api.tavily.com/mcp")

        # Capture the auth_query_params passed to _initialize_gateway
        captured_params = {}

        async def capture_init(*args, **kwargs):
            captured_params.update(kwargs.get("auth_query_params", {}) or {})
            return ({"tools": {"listChanged": True}}, [], [], [])

        gateway_service._initialize_gateway = AsyncMock(side_effect=capture_init)
        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "tavily_gateway"
        mock_model.url = url
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(
            name="tavily_gateway",
            url=url,
            auth_type="query_param",
            auth_query_param_key="tavilyApiKey",
            auth_query_param_value="secret-api-key-123",
        )

        await gateway_service.register_gateway(test_db, gateway_create)

        # Verify _initialize_gateway was called with decrypted params
        gateway_service._initialize_gateway.assert_called_once()
        call_kwargs = gateway_service._initialize_gateway.call_args[1]
        assert "auth_query_params" in call_kwargs
        assert call_kwargs["auth_query_params"] == {"tavilyApiKey": "secret-api-key-123"}


class TestQueryParamAuthUrlHelpers:
    """Tests for URL helper functions with query param auth."""

    def test_apply_query_param_auth_adds_param(self):
        """Test that apply_query_param_auth correctly adds the param to URL."""
        url = "https://api.tavily.com/mcp"
        params = {"tavilyApiKey": "secret123"}
        result = apply_query_param_auth(url, params)
        assert result == "https://api.tavily.com/mcp?tavilyApiKey=secret123"

    def test_apply_query_param_auth_appends_to_existing(self):
        """Test that apply_query_param_auth appends to existing params."""
        url = "https://api.example.com/search?q=test"
        params = {"api_key": "secret"}
        result = apply_query_param_auth(url, params)
        assert "q=test" in result
        assert "api_key=secret" in result

    def test_sanitize_url_redacts_auth_param(self):
        """Test that sanitize_url_for_logging redacts the auth param."""
        url = "https://api.tavily.com/mcp?tavilyApiKey=secret123"
        params = {"tavilyApiKey": "secret123"}
        result = sanitize_url_for_logging(url, params)
        assert "tavilyApiKey=REDACTED" in result
        assert "secret123" not in result

    def test_sanitize_url_preserves_non_sensitive_params(self):
        """Test that non-sensitive params are preserved."""
        url = "https://api.example.com?page=1&api_key=secret"
        result = sanitize_url_for_logging(url)
        assert "page=1" in result
        assert "api_key=REDACTED" in result


class TestQueryParamAuthUpdate:
    """Tests for updating gateways with query_param authentication."""

    @pytest.mark.asyncio
    async def test_update_gateway_add_query_param_auth(self, gateway_service, test_db, monkeypatch):
        """Test updating a gateway to add query_param auth."""
        # Create mock existing gateway without auth
        mock_gateway = MagicMock()
        mock_gateway.id = "gateway-123"
        mock_gateway.name = "tavily_gateway"
        mock_gateway.url = "https://api.tavily.com/mcp"
        mock_gateway.auth_type = None
        mock_gateway.auth_value = None
        mock_gateway.auth_query_params = None
        mock_gateway.is_active = True
        mock_gateway.transport = "sse"
        mock_gateway.oauth_config = None
        mock_gateway.ca_certificate = None
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=mock_gateway),  # fetch gateway
                _make_execute_result(scalar=None),  # name conflict check
            ]
        )

        gateway_service._initialize_gateway = AsyncMock(
            return_value=({"tools": {"listChanged": True}}, [], [], [])
        )
        gateway_service._notify_gateway_changed = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_update = GatewayUpdate(
            auth_type="query_param",
            auth_query_param_key="tavilyApiKey",
            auth_query_param_value="new-secret-key",
        )

        await gateway_service.update_gateway(test_db, "gateway-123", gateway_update)

        # Verify auth_type was updated
        assert mock_gateway.auth_type == "query_param"
        # Verify auth_query_params was set with encrypted value
        assert mock_gateway.auth_query_params is not None
        assert "tavilyApiKey" in mock_gateway.auth_query_params  # pylint: disable=unsupported-membership-test

    def test_gateway_update_schema_allows_query_param_fields(self, mock_all_settings):
        """Test that GatewayUpdate schema accepts query_param auth fields."""
        gateway_update = GatewayUpdate(
            auth_type="query_param",
            auth_query_param_key="tavilyApiKey",
            auth_query_param_value="new-secret-key",
        )
        assert gateway_update.auth_type == "query_param"
        assert gateway_update.auth_query_param_key == "tavilyApiKey"
        # auth_query_param_value is a SecretStr, so we need to get the secret value
        assert gateway_update.auth_query_param_value.get_secret_value() == "new-secret-key"


class TestQueryParamAuthFeatureFlag:
    """Tests for INSECURE_ALLOW_QUERY_PARAM_AUTH feature flag."""

    def test_gateway_create_schema_accepts_query_param_when_enabled(self, mock_all_settings):
        """Test that GatewayCreate accepts query_param auth when flag is enabled."""
        # The autouse fixture already enables query_param auth
        gateway = GatewayCreate(
            name="test_gateway",
            url="https://api.example.com/mcp",
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value="secret",
        )
        assert gateway.auth_type == "query_param"
        assert gateway.auth_query_param_key == "api_key"

    def test_gateway_create_rejects_host_not_in_allowlist(self):
        """Test that GatewayCreate rejects hosts not in the allowlist."""
        # Use a fresh patch context to control settings precisely
        with patch("mcpgateway.schemas.settings") as schema_settings:
            schema_settings.insecure_allow_queryparam_auth = True  # Note: no underscore before queryparam
            schema_settings.insecure_queryparam_auth_allowed_hosts = ["mcp.tavily.com"]
            schema_settings.masked_auth_value = "*****"

            with pytest.raises(ValueError, match="not in the allowed hosts"):
                GatewayCreate(
                    name="test_gateway",
                    url="https://api.example.com/mcp",
                    auth_type="query_param",
                    auth_query_param_key="api_key",
                    auth_query_param_value="secret",
                )

    def test_gateway_create_schema_rejects_query_param_when_disabled(self):
        """Test that GatewayCreate rejects query_param auth when flag is disabled."""
        # Use a fresh patch context to control settings precisely
        with patch("mcpgateway.schemas.settings") as schema_settings:
            schema_settings.insecure_allow_queryparam_auth = False  # Note: no underscore before queryparam
            schema_settings.insecure_queryparam_auth_allowed_hosts = []
            schema_settings.masked_auth_value = "*****"

            with pytest.raises(ValueError, match="authentication is disabled"):
                GatewayCreate(
                    name="test_gateway",
                    url="https://api.example.com/mcp",
                    auth_type="query_param",
                    auth_query_param_key="api_key",
                    auth_query_param_value="secret",
                )
