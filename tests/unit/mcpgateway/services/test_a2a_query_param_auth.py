# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_query_param_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for query parameter authentication in A2AService.

Tests the query_param auth_type which stores encrypted API keys for
upstream A2A agents that require query parameter authentication.

Security Note:
    Query parameter authentication is inherently insecure (CWE-598).
    These tests verify that:
    1. Auth params are properly encrypted at rest
    2. The INSECURE_ALLOW_QUERY_PARAM_AUTH feature flag is respected
    3. Host allowlist is enforced
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import A2AAgentCreate, A2AAgentRead, A2AAgentUpdate
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.utils.services_auth import decode_auth


def _make_execute_result(*, scalar=None, scalars_list=None):
    """Return a MagicMock that behaves like SQLAlchemy Result object."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


@pytest.fixture
def a2a_service():
    """Create an A2AAgentService instance."""
    return A2AAgentService()


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
    """Mock structured_logger to prevent database writes."""
    with patch("mcpgateway.services.a2a_service.structured_logger") as mock_logger:
        mock_logger.log = MagicMock(return_value=None)
        mock_logger.info = MagicMock(return_value=None)
        mock_logger.warning = MagicMock(return_value=None)
        yield {"structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def _bypass_a2aagentread_validation(monkeypatch):
    """Stub A2AAgentRead.model_validate to return input unchanged."""
    monkeypatch.setattr(A2AAgentRead, "model_validate", staticmethod(lambda x: x))


@pytest.fixture(autouse=True)
def mock_all_settings():
    """Mock settings in schemas, a2a_service, and config modules."""
    with patch("mcpgateway.schemas.settings") as schema_settings, \
         patch("mcpgateway.config.settings") as config_settings:
        # Configure schema settings
        schema_settings.insecure_allow_queryparam_auth = True
        schema_settings.insecure_queryparam_auth_allowed_hosts = ["api.tavily.com", "mcp.tavily.com", "api.example.com"]
        schema_settings.masked_auth_value = "*****"

        # Configure config settings (used by service layer imports)
        config_settings.insecure_allow_queryparam_auth = True
        config_settings.insecure_queryparam_auth_allowed_hosts = ["api.tavily.com", "mcp.tavily.com", "api.example.com"]
        config_settings.masked_auth_value = "*****"

        yield {"schema": schema_settings, "config": config_settings}


@pytest.fixture(autouse=True)
def mock_cache_invalidation():
    """Mock cache invalidation to avoid side effects."""
    with patch("mcpgateway.services.a2a_service.a2a_stats_cache") as mock_stats, \
         patch("mcpgateway.services.a2a_service._get_registry_cache") as mock_registry:
        mock_stats.invalidate = MagicMock()
        mock_cache = AsyncMock()
        mock_registry.return_value = mock_cache
        yield {"stats_cache": mock_stats, "registry_cache": mock_cache}


@pytest.fixture(autouse=True)
def mock_admin_stats_cache():
    """Mock admin_stats_cache to avoid import errors."""
    mock_cache = MagicMock()
    mock_cache.invalidate_tags = AsyncMock()
    with patch.dict("sys.modules", {"mcpgateway.cache.admin_stats_cache": MagicMock(admin_stats_cache=mock_cache)}):
        yield mock_cache


@pytest.fixture(autouse=True)
def mock_metrics_cache():
    """Mock metrics_cache to avoid import errors."""
    mock_cache = MagicMock()
    mock_cache.invalidate = MagicMock()
    with patch.dict("sys.modules", {"mcpgateway.cache.metrics_cache": MagicMock(metrics_cache=mock_cache)}):
        yield mock_cache


class TestA2AQueryParamAuthRegistration:
    """Tests for registering A2A agents with query_param authentication."""

    @pytest.mark.asyncio
    async def test_register_agent_with_query_param_auth(self, a2a_service, test_db, monkeypatch):
        """Test registering an agent with query_param auth encrypts the params."""
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # slug conflict check
            ]
        )

        # Mock convert_agent_to_read
        mock_read = Mock()
        mock_read.masked.return_value = mock_read
        monkeypatch.setattr(a2a_service, "convert_agent_to_read", Mock(return_value=mock_read))

        # Mock ToolService.create_tool_from_a2a_agent
        with patch("mcpgateway.services.a2a_service.ToolService") as mock_tool_service:
            mock_tool_service.return_value.create_tool_from_a2a_agent = AsyncMock(return_value=None)

            agent_create = A2AAgentCreate(
                name="tavily_agent",
                endpoint_url="https://api.tavily.com/a2a",
                agent_type="task",
                protocol_version="1.0",
                capabilities={},
                config={},
                auth_type="query_param",
                auth_query_param_key="tavilyApiKey",
                auth_query_param_value="secret-api-key-123",
            )

            await a2a_service.register_agent(test_db, agent_create)

            # Verify the agent was added to the database
            test_db.add.assert_called_once()
            added_agent = test_db.add.call_args[0][0]

            # Verify auth_type is set correctly
            assert added_agent.auth_type == "query_param"

            # Verify auth_query_params is encrypted (stored as dict with encrypted values)
            assert added_agent.auth_query_params is not None
            assert "tavilyApiKey" in added_agent.auth_query_params

            # The value should be encrypted, not plaintext
            encrypted_value = added_agent.auth_query_params["tavilyApiKey"]
            assert encrypted_value != "secret-api-key-123"

            # Verify decryption yields original value
            decrypted = decode_auth(encrypted_value)
            assert decrypted.get("tavilyApiKey") == "secret-api-key-123"

    @pytest.mark.asyncio
    async def test_register_agent_query_param_clears_auth_value(self, a2a_service, test_db, monkeypatch):
        """Test that query_param auth sets auth_value to None."""
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # slug conflict check
            ]
        )

        mock_read = Mock()
        mock_read.masked.return_value = mock_read
        monkeypatch.setattr(a2a_service, "convert_agent_to_read", Mock(return_value=mock_read))

        with patch("mcpgateway.services.a2a_service.ToolService") as mock_tool_service:
            mock_tool_service.return_value.create_tool_from_a2a_agent = AsyncMock(return_value=None)

            agent_create = A2AAgentCreate(
                name="test_agent",
                endpoint_url="https://api.example.com/a2a",
                agent_type="task",
                protocol_version="1.0",
                capabilities={},
                config={},
                auth_type="query_param",
                auth_query_param_key="api_key",
                auth_query_param_value="secret123",
            )

            await a2a_service.register_agent(test_db, agent_create)

            added_agent = test_db.add.call_args[0][0]
            # Query param auth should not use auth_value
            assert added_agent.auth_value is None


class TestA2AQueryParamAuthUpdate:
    """Tests for updating A2A agents with query_param authentication."""

    @pytest.mark.asyncio
    async def test_update_agent_add_query_param_auth(self, a2a_service, test_db, monkeypatch):
        """Test updating an agent to add query_param auth."""
        # Create mock existing agent without auth
        mock_agent = MagicMock()
        mock_agent.id = "agent-123"
        mock_agent.name = "test_agent"
        mock_agent.slug = "test_agent"
        mock_agent.endpoint_url = "https://api.tavily.com/a2a"
        mock_agent.auth_type = None
        mock_agent.auth_value = None
        mock_agent.auth_query_params = None
        mock_agent.enabled = True
        mock_agent.version = 1
        mock_agent.visibility = "public"
        mock_agent.team_id = None
        mock_agent.owner_email = None
        mock_agent.passthrough_headers = None
        mock_agent.__table__ = MagicMock()
        mock_agent.__table__.columns = []

        # Mock get_for_update to return the agent
        with patch("mcpgateway.services.a2a_service.get_for_update") as mock_get:
            mock_get.return_value = mock_agent

            mock_read = Mock()
            mock_read.masked.return_value = mock_read
            monkeypatch.setattr(a2a_service, "convert_agent_to_read", Mock(return_value=mock_read))

            with patch("mcpgateway.services.a2a_service.ToolService") as mock_tool_service:
                mock_tool_service.return_value.update_tool_from_a2a_agent = AsyncMock()

                agent_update = A2AAgentUpdate(
                    auth_type="query_param",
                    auth_query_param_key="tavilyApiKey",
                    auth_query_param_value="new-secret-key",
                )

                await a2a_service.update_agent(test_db, "agent-123", agent_update)

                # Verify auth_type was updated
                assert mock_agent.auth_type == "query_param"
                # Verify auth_query_params was set with encrypted value
                assert mock_agent.auth_query_params is not None
                assert "tavilyApiKey" in mock_agent.auth_query_params

    @pytest.mark.asyncio
    async def test_update_agent_clear_query_param_auth_when_switching(self, a2a_service, test_db, monkeypatch):
        """Test that switching away from query_param clears auth_query_params."""
        # Create mock existing agent with query_param auth
        mock_agent = MagicMock()
        mock_agent.id = "agent-123"
        mock_agent.name = "test_agent"
        mock_agent.slug = "test_agent"
        mock_agent.endpoint_url = "https://api.tavily.com/a2a"
        mock_agent.auth_type = "query_param"
        mock_agent.auth_value = None
        mock_agent.auth_query_params = {"tavilyApiKey": "encrypted_value"}
        mock_agent.enabled = True
        mock_agent.version = 1
        mock_agent.visibility = "public"
        mock_agent.team_id = None
        mock_agent.owner_email = None
        mock_agent.passthrough_headers = None
        mock_agent.__table__ = MagicMock()
        mock_agent.__table__.columns = []

        with patch("mcpgateway.services.a2a_service.get_for_update") as mock_get:
            mock_get.return_value = mock_agent

            mock_read = Mock()
            mock_read.masked.return_value = mock_read
            monkeypatch.setattr(a2a_service, "convert_agent_to_read", Mock(return_value=mock_read))

            with patch("mcpgateway.services.a2a_service.ToolService") as mock_tool_service:
                mock_tool_service.return_value.update_tool_from_a2a_agent = AsyncMock()

                agent_update = A2AAgentUpdate(
                    auth_type="bearer",
                    auth_token="my-bearer-token",
                )

                await a2a_service.update_agent(test_db, "agent-123", agent_update)

                # Verify auth_query_params was cleared
                assert mock_agent.auth_query_params is None


class TestA2AQueryParamAuthSchemaValidation:
    """Tests for A2A schema validation with query_param authentication."""

    def test_a2a_agent_create_schema_accepts_query_param(self, mock_all_settings):
        """Test that A2AAgentCreate accepts query_param auth when flag is enabled."""
        agent = A2AAgentCreate(
            name="test_agent",
            endpoint_url="https://api.example.com/a2a",
            agent_type="task",
            protocol_version="1.0",
            capabilities={},
            config={},
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value="secret",
        )
        assert agent.auth_type == "query_param"
        assert agent.auth_query_param_key == "api_key"

    def test_a2a_agent_create_rejects_host_not_in_allowlist(self):
        """Test that A2AAgentCreate rejects hosts not in the allowlist."""
        with patch("mcpgateway.schemas.settings") as schema_settings:
            schema_settings.insecure_allow_queryparam_auth = True
            schema_settings.insecure_queryparam_auth_allowed_hosts = ["mcp.tavily.com"]
            schema_settings.masked_auth_value = "*****"

            with pytest.raises(ValueError, match="not in the allowed hosts"):
                A2AAgentCreate(
                    name="test_agent",
                    endpoint_url="https://unauthorized.example.com/a2a",
                    agent_type="task",
                    protocol_version="1.0",
                    capabilities={},
                    config={},
                    auth_type="query_param",
                    auth_query_param_key="api_key",
                    auth_query_param_value="secret",
                )

    def test_a2a_agent_create_rejects_query_param_when_disabled(self):
        """Test that A2AAgentCreate rejects query_param auth when flag is disabled."""
        with patch("mcpgateway.schemas.settings") as schema_settings:
            schema_settings.insecure_allow_queryparam_auth = False
            schema_settings.insecure_queryparam_auth_allowed_hosts = []
            schema_settings.masked_auth_value = "*****"

            with pytest.raises(ValueError, match="authentication is disabled"):
                A2AAgentCreate(
                    name="test_agent",
                    endpoint_url="https://api.example.com/a2a",
                    agent_type="task",
                    protocol_version="1.0",
                    capabilities={},
                    config={},
                    auth_type="query_param",
                    auth_query_param_key="api_key",
                    auth_query_param_value="secret",
                )

    def test_a2a_agent_update_schema_allows_query_param_fields(self, mock_all_settings):
        """Test that A2AAgentUpdate schema accepts query_param auth fields."""
        agent_update = A2AAgentUpdate(
            auth_type="query_param",
            auth_query_param_key="tavilyApiKey",
            auth_query_param_value="new-secret-key",
        )
        assert agent_update.auth_type == "query_param"
        assert agent_update.auth_query_param_key == "tavilyApiKey"
        # auth_query_param_value is a SecretStr
        assert agent_update.auth_query_param_value.get_secret_value() == "new-secret-key"


class TestA2AAgentReadQueryParamMasking:
    """Tests for A2AAgentRead query_param auth masking."""

    @pytest.fixture(autouse=True)
    def _restore_a2aagentread_validation(self, monkeypatch):
        """Restore original A2AAgentRead.model_validate for masking tests."""
        # Restore the original model_validate by getting it from BaseModel
        from pydantic import BaseModel

        # The base Pydantic behavior will then be used
        monkeypatch.setattr(A2AAgentRead, "model_validate", classmethod(lambda cls, obj, **kwargs: BaseModel.model_validate.__func__(cls, obj, **kwargs)))

    def test_a2a_agent_read_masks_query_param_from_dict(self):
        """Test that A2AAgentRead masks query param value from dict input."""
        # Need to patch settings for the validator
        with patch("mcpgateway.schemas.settings") as schema_settings:
            schema_settings.masked_auth_value = "*****"

            data = {
                "id": "agent-123",
                "name": "test_agent",
                "slug": "test_agent",
                "endpoint_url": "https://api.tavily.com/a2a",
                "agent_type": "task",
                "protocol_version": "1.0",
                "capabilities": {},
                "config": {},
                "enabled": True,
                "reachable": True,
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
                "last_interaction": None,
                "auth_type": "query_param",
                "auth_query_params": {"tavilyApiKey": "encrypted_secret"},
            }

            agent_read = A2AAgentRead.model_validate(data)
            assert agent_read.auth_query_param_key == "tavilyApiKey"
            assert agent_read.auth_query_param_value_masked == "*****"
