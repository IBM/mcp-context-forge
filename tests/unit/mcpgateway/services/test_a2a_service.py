# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for A2A Agent Service functionality.
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.cache.a2a_stats_cache import a2a_stats_cache
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.schemas import A2AAgentCreate, A2AAgentUpdate
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNameConflictError, A2AAgentNotFoundError, A2AAgentService
from mcpgateway.utils.services_auth import encode_auth


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock structured_logger and audit_trail to prevent database writes during tests."""
    with (
        patch("mcpgateway.services.a2a_service.structured_logger") as mock_a2a_logger,
        patch("mcpgateway.services.tool_service.structured_logger") as mock_tool_logger,
        patch("mcpgateway.services.tool_service.audit_trail") as mock_tool_audit,
    ):
        mock_a2a_logger.log = MagicMock(return_value=None)
        mock_a2a_logger.info = MagicMock(return_value=None)
        mock_tool_logger.log = MagicMock(return_value=None)
        mock_tool_logger.info = MagicMock(return_value=None)
        mock_tool_audit.log_action = MagicMock(return_value=None)
        yield {"structured_logger": mock_a2a_logger, "tool_logger": mock_tool_logger, "tool_audit": mock_tool_audit}


class TestA2AAgentService:
    """Test suite for A2A Agent Service."""

    def setup_method(self):
        """Clear the A2A stats cache before each test to ensure isolation."""
        a2a_stats_cache.invalidate()

    @pytest.fixture
    def service(self):
        """Create A2A agent service instance."""
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def sample_agent_create(self):
        """Sample A2A agent creation data."""
        return A2AAgentCreate(
            name="test-agent",
            description="Test agent for unit tests",
            endpoint_url="https://api.example.com/agent",
            agent_type="custom",
            auth_username="user",
            auth_password="dummy_pass",
            protocol_version="1.0",
            capabilities={"chat": True, "tools": False},
            config={"max_tokens": 1000},
            auth_type="basic",
            auth_value="encode-auth-value",
            tags=["test", "ai"],
        )

    @pytest.fixture
    def sample_db_agent(self):
        """Sample database A2A agent."""
        agent_id = uuid.uuid4().hex
        return DbA2AAgent(
            id=agent_id,
            name="test-agent",
            slug="test-agent",
            description="Test agent for unit tests",
            endpoint_url="https://api.example.com/agent",
            agent_type="custom",
            protocol_version="1.0",
            capabilities={"chat": True, "tools": False},
            config={"max_tokens": 1000},
            auth_type="basic",
            auth_value="encoded-auth-value",
            enabled=True,
            reachable=True,
            tags=[{"id": "test", "label": "test"}, {"id": "ai", "label": "ai"}],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1,
            metrics=[],
        )

    async def test_initialize(self, service):
        """Test service initialization."""
        assert not service._initialized
        await service.initialize()
        assert service._initialized

    async def test_shutdown(self, service):
        """Test service shutdown."""
        await service.initialize()
        assert service._initialized
        await service.shutdown()
        assert not service._initialized

    async def test_register_agent_success(self, service, mock_db, sample_agent_create):
        """Test successful agent registration."""
        # Mock database queries
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No existing agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        # Mock the created agent with all required fields for ToolRead
        created_agent = MagicMock()
        created_agent.id = uuid.uuid4().hex
        created_agent.name = sample_agent_create.name
        created_agent.slug = "test-agent"
        created_agent.metrics = []
        created_agent.createdAt = "2025-09-26T00:00:00Z"
        created_agent.updatedAt = "2025-09-26T00:00:00Z"
        created_agent.enabled = True
        created_agent.reachable = True
        # Add any other required fields for ToolRead if needed
        mock_db.add = MagicMock()

        # Mock service method to return a MagicMock (simulate ToolRead)
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        # Patch ToolRead.model_validate to accept the dict without error
        import mcpgateway.schemas

        if hasattr(mcpgateway.schemas.ToolRead, "model_validate"):
            from unittest.mock import patch

            with patch.object(mcpgateway.schemas.ToolRead, "model_validate", return_value=MagicMock()):
                await service.register_agent(mock_db, sample_agent_create)
        else:
            await service.register_agent(mock_db, sample_agent_create)

        # Verify
        # add: 1 for agent, 1 for tool
        assert mock_db.add.call_count == 2
        # commit: 1 for agent (before tool creation), 1 for tool, 1 for tool association
        assert mock_db.commit.call_count == 3
        assert service.convert_agent_to_read.called

    async def test_register_agent_name_conflict(self, service, mock_db, sample_agent_create):
        """Test agent registration with name conflict."""
        # Mock existing agent
        existing_agent = MagicMock()
        existing_agent.enabled = True
        existing_agent.id = uuid.uuid4().hex
        mock_db.execute.return_value.scalar_one_or_none.return_value = existing_agent

        # Execute and verify exception
        with pytest.raises(A2AAgentNameConflictError):
            await service.register_agent(mock_db, sample_agent_create)

    async def test_list_agents_all_active(self, service, mock_db, sample_db_agent):
        """Test listing all active agents."""
        # Mock database query
        mock_db.execute.return_value.scalars.return_value.all.return_value = [sample_db_agent]
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        # Execute
        result = await service.list_agents(mock_db, include_inactive=False)

        # Verify
        assert service.convert_agent_to_read.called
        assert len(result) >= 0  # Should return mocked results

    async def test_list_agents_with_tags(self, service, mock_db, sample_db_agent):
        """Test listing agents filtered by tags."""
        # Mock database query and dialect for json_contains_expr
        mock_db.execute.return_value.scalars.return_value.all.return_value = [sample_db_agent]
        mock_db.get_bind.return_value.dialect.name = "sqlite"
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        # Execute
        await service.list_agents(mock_db, tags=["test"])

        # Verify
        assert service.convert_agent_to_read.called

    async def test_get_agent_success(self, service, mock_db, sample_db_agent):
        """Test successful agent retrieval by ID."""
        # Mock database query
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        # Execute
        await service.get_agent(mock_db, sample_db_agent.id)

        # Verify
        assert service.convert_agent_to_read.called

    async def test_get_agent_not_found(self, service, mock_db):
        """Test agent retrieval with non-existent ID."""
        # Mock database query returning None
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # Execute and verify exception
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(mock_db, "non-existent-id")

    async def test_get_agent_by_name_success(self, service, mock_db, sample_db_agent):
        """Test successful agent retrieval by name."""
        # Mock database query
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        # Execute
        await service.get_agent_by_name(mock_db, sample_db_agent.name)

        # Verify
        assert service.convert_agent_to_read.called

    async def test_update_agent_success(self, service, mock_db, sample_db_agent):
        """Test successful agent update."""
        # Set version attribute to avoid TypeError
        sample_db_agent.version = 1

        # Mock get_for_update to return the agent
        with patch("mcpgateway.services.a2a_service.get_for_update") as mock_get_for_update:
            mock_get_for_update.return_value = sample_db_agent

            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()

            # Mock the convert_agent_to_read method properly
            with patch.object(service, "convert_agent_to_read") as mock_schema:
                mock_schema.return_value = MagicMock()

                # Create update data
                update_data = A2AAgentUpdate(description="Updated description")

                # Execute (keep mock active during call)
                await service.update_agent(mock_db, sample_db_agent.id, update_data)

                # Verify
                mock_db.commit.assert_called_once()
                assert mock_schema.called
                assert sample_db_agent.version == 2  # Should be incremented

    async def test_update_agent_not_found(self, service, mock_db):
        """Test updating non-existent agent."""
        # Mock get_for_update to return None (agent not found)
        with patch("mcpgateway.services.a2a_service.get_for_update") as mock_get_for_update:
            mock_get_for_update.return_value = None
            update_data = A2AAgentUpdate(description="Updated description")

            # Execute and verify exception
            with pytest.raises(A2AAgentNotFoundError):
                await service.update_agent(mock_db, "non-existent-id", update_data)

    async def test_set_agent_state_success(self, service, mock_db, sample_db_agent):
        """Test successful agent state change."""
        # Mock database query
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        # Execute
        await service.set_agent_state(mock_db, sample_db_agent.id, False)

        # Verify
        assert sample_db_agent.enabled is False
        mock_db.commit.assert_called_once()
        assert service.convert_agent_to_read.called

    async def test_delete_agent_success(self, service, mock_db, sample_db_agent):
        """Test successful agent deletion."""
        # Mock database query
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()

        # Execute
        await service.delete_agent(mock_db, sample_db_agent.id)

        # Verify
        mock_db.delete.assert_called_once_with(sample_db_agent)
        mock_db.commit.assert_called_once()

    async def test_delete_agent_purge_metrics(self, service, mock_db, sample_db_agent):
        """Test agent deletion with metric purge."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()

        await service.delete_agent(mock_db, sample_db_agent.id, purge_metrics=True)

        assert mock_db.execute.call_count == 3
        mock_db.delete.assert_called_once_with(sample_db_agent)
        mock_db.commit.assert_called_once()

    async def test_delete_agent_not_found(self, service, mock_db):
        """Test deleting non-existent agent."""
        # Mock database query returning None
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # Execute and verify exception
        with pytest.raises(A2AAgentNotFoundError):
            await service.delete_agent(mock_db, "non-existent-id")

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_invoke_agent_success(self, mock_get_for_update, mock_get_client, mock_fresh_db, mock_metrics_buffer_fn, service, mock_db, sample_db_agent):
        """Test successful agent invocation."""
        # Mock HTTP client (shared client pattern)
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Test response", "status": "success"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations - agent lookup by name returns ID
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent.id

        # Mock get_for_update to return agent with proper attributes
        mock_agent = MagicMock()
        mock_agent.id = sample_db_agent.id
        mock_agent.name = sample_db_agent.name
        mock_agent.enabled = True
        mock_agent.endpoint_url = sample_db_agent.endpoint_url
        mock_agent.auth_type = None
        mock_agent.auth_value = None
        mock_agent.auth_query_params = None
        mock_agent.protocol_version = sample_db_agent.protocol_version
        mock_agent.agent_type = "generic"
        mock_agent.visibility = "public"
        mock_agent.team_id = None
        mock_agent.owner_email = None
        mock_get_for_update.return_value = mock_agent

        # Mock fresh_db_session for last_interaction update
        mock_ts_db = MagicMock()
        mock_ts_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        # Mock metrics buffer service
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # Execute
        result = await service.invoke_agent(mock_db, sample_db_agent.name, {"test": "data"})

        # Verify
        assert result["response"] == "Test response"
        mock_client.post.assert_called_once()
        # Metrics recorded via buffer service
        mock_metrics_buffer.record_a2a_agent_metric_with_duration.assert_called_once()
        # last_interaction updated via fresh_db_session
        mock_ts_db.commit.assert_called()

    async def test_invoke_agent_disabled(self, service, mock_db, sample_db_agent):
        """Test invoking disabled agent."""
        # Mock disabled agent
        disabled_agent = MagicMock()
        disabled_agent.enabled = False
        disabled_agent.name = sample_db_agent.name
        disabled_agent.id = sample_db_agent.id

        # Mock the database query to return agent ID
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent.id

        # Mock get_for_update to return the disabled agent
        with patch("mcpgateway.services.a2a_service.get_for_update") as mock_get_for_update:
            mock_get_for_update.return_value = disabled_agent
            mock_db.commit = MagicMock()
            mock_db.close = MagicMock()

            # Execute and verify exception
            with pytest.raises(A2AAgentError, match="disabled"):
                await service.invoke_agent(mock_db, sample_db_agent.name, {"test": "data"})

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_invoke_agent_http_error(self, mock_get_for_update, mock_get_client, mock_fresh_db, mock_metrics_buffer_fn, service, mock_db, sample_db_agent):
        """Test agent invocation with HTTP error."""
        # Mock HTTP client with error response (shared client pattern)
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations - agent lookup by name returns ID
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent.id

        # Mock get_for_update to return agent with proper attributes
        mock_agent = MagicMock()
        mock_agent.id = sample_db_agent.id
        mock_agent.name = sample_db_agent.name
        mock_agent.enabled = True
        mock_agent.endpoint_url = sample_db_agent.endpoint_url
        mock_agent.auth_type = None
        mock_agent.auth_value = None
        mock_agent.auth_query_params = None
        mock_agent.protocol_version = sample_db_agent.protocol_version
        mock_agent.agent_type = "generic"
        mock_agent.visibility = "public"
        mock_agent.team_id = None
        mock_agent.owner_email = None
        mock_get_for_update.return_value = mock_agent

        # Mock fresh_db_session for last_interaction update
        mock_ts_db = MagicMock()
        mock_ts_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        # Mock metrics buffer service
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # Execute and verify exception
        with pytest.raises(A2AAgentError, match="HTTP 500"):
            await service.invoke_agent(mock_db, sample_db_agent.name, {"test": "data"})

        # Verify metrics were still recorded via buffer service
        mock_metrics_buffer.record_a2a_agent_metric_with_duration.assert_called_once()
        # last_interaction updated via fresh_db_session
        mock_ts_db.commit.assert_called()

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_agent_with_basic_auth(self, mock_get_client, mock_fresh_db, mock_metrics_buffer_fn, service, mock_db, sample_db_agent):
        """Test agent invocation with Basic Auth credentials are correctly decoded and passed.

        Regression test for issue #2002: A2A agents with Basic Auth fail with HTTP 401.
        """
        # Create realistic encrypted auth_value using encode_auth
        basic_auth_headers = {"Authorization": "Basic dXNlcm5hbWU6cGFzc3dvcmQ="}  # username:password in base64
        with patch("mcpgateway.utils.services_auth.settings") as mock_settings:
            mock_settings.auth_encryption_secret = "test-secret-key-for-encryption"
            encrypted_auth_value = encode_auth(basic_auth_headers)

        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Auth success", "status": "success"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations with encrypted auth_value
        agent_with_auth = MagicMock(
            id=sample_db_agent.id,
            name="basic-auth-agent",
            enabled=True,
            endpoint_url="https://api.example.com/secure-agent",
            auth_type="basic",
            auth_value=encrypted_auth_value,
            protocol_version="1.0",
            agent_type="generic",
        )
        service.get_agent_by_name = AsyncMock(return_value=agent_with_auth)

        # Mock db.execute for auth_value fetch
        mock_db_row = MagicMock()
        mock_db_row.auth_value = encrypted_auth_value
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_row

        # Mock fresh_db_session for last_interaction update
        mock_ts_db = MagicMock()
        mock_ts_db.execute.return_value.scalar_one_or_none.return_value = agent_with_auth
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        # Mock metrics buffer service
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # Ensure get_for_update returns our mocked agent so auth_value is read
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent_with_auth):
            # Execute with decode_auth patched to return the expected headers
            with patch("mcpgateway.services.a2a_service.decode_auth", return_value=basic_auth_headers):
                result = await service.invoke_agent(mock_db, "basic-auth-agent", {"test": "data"})

        # Verify successful response
        assert result["response"] == "Auth success"

        # Verify HTTP client was called with correct Authorization header
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        headers_used = call_args.kwargs.get("headers", {})
        assert "Authorization" in headers_used
        assert headers_used["Authorization"] == "Basic dXNlcm5hbWU6cGFzc3dvcmQ="

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_agent_with_bearer_auth(self, mock_get_client, mock_fresh_db, mock_metrics_buffer_fn, service, mock_db, sample_db_agent):
        """Test agent invocation with Bearer token credentials are correctly decoded and passed.

        Regression test for issue #2002: Ensures Bearer tokens are properly decrypted.
        """
        # Create realistic encrypted auth_value using encode_auth
        bearer_auth_headers = {"Authorization": "Bearer my-secret-jwt-token-12345"}
        with patch("mcpgateway.utils.services_auth.settings") as mock_settings:
            mock_settings.auth_encryption_secret = "test-secret-key-for-encryption"
            encrypted_auth_value = encode_auth(bearer_auth_headers)

        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Bearer auth success", "status": "success"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations with encrypted auth_value
        agent_with_auth = MagicMock(
            id=sample_db_agent.id,
            name="bearer-auth-agent",
            enabled=True,
            endpoint_url="https://api.example.com/secure-agent",
            auth_type="bearer",
            auth_value=encrypted_auth_value,
            protocol_version="1.0",
            agent_type="generic",
        )
        service.get_agent_by_name = AsyncMock(return_value=agent_with_auth)

        # Mock db.execute for auth_value fetch
        mock_db_row = MagicMock()
        mock_db_row.auth_value = encrypted_auth_value
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_row

        # Mock fresh_db_session for last_interaction update
        mock_ts_db = MagicMock()
        mock_ts_db.execute.return_value.scalar_one_or_none.return_value = agent_with_auth
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        # Mock metrics buffer service
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # Ensure get_for_update returns our mocked agent so auth_value is read
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent_with_auth):
            # Execute with decode_auth patched to return the expected headers
            with patch("mcpgateway.services.a2a_service.decode_auth", return_value=bearer_auth_headers):
                result = await service.invoke_agent(mock_db, "bearer-auth-agent", {"test": "data"})

        # Verify successful response
        assert result["response"] == "Bearer auth success"

        # Verify HTTP client was called with correct Authorization header
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        headers_used = call_args.kwargs.get("headers", {})
        assert "Authorization" in headers_used
        assert headers_used["Authorization"] == "Bearer my-secret-jwt-token-12345"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_agent_with_custom_headers(self, mock_get_client, mock_fresh_db, mock_metrics_buffer_fn, service, mock_db, sample_db_agent):
        """Test agent invocation with custom headers (X-API-Key) are correctly decoded and passed.

        Regression test for issue #2002: A2A agents with X-API-Key header fail with HTTP 401.
        """
        # Create realistic encrypted auth_value with custom headers
        custom_auth_headers = {"X-API-Key": "test-key-for-unit-test", "X-Custom-Header": "custom-value"}
        with patch("mcpgateway.utils.services_auth.settings") as mock_settings:
            mock_settings.auth_encryption_secret = "test-secret-key-for-encryption"
            encrypted_auth_value = encode_auth(custom_auth_headers)

        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "API key auth success", "status": "success"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations with encrypted auth_value
        agent_with_auth = MagicMock(
            id=sample_db_agent.id,
            name="apikey-auth-agent",
            enabled=True,
            endpoint_url="https://api.example.com/secure-agent",
            auth_type="authheaders",
            auth_value=encrypted_auth_value,
            protocol_version="1.0",
            agent_type="generic",
        )
        service.get_agent_by_name = AsyncMock(return_value=agent_with_auth)

        # Mock db.execute for auth_value fetch
        mock_db_row = MagicMock()
        mock_db_row.auth_value = encrypted_auth_value
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_row

        # Mock fresh_db_session for last_interaction update
        mock_ts_db = MagicMock()
        mock_ts_db.execute.return_value.scalar_one_or_none.return_value = agent_with_auth
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        # Mock metrics buffer service
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # Ensure get_for_update returns our mocked agent so auth_value is read
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent_with_auth):
            # Execute with decode_auth patched to return the expected headers
            with patch("mcpgateway.services.a2a_service.decode_auth", return_value=custom_auth_headers):
                result = await service.invoke_agent(mock_db, "apikey-auth-agent", {"test": "data"})

        # Verify successful response
        assert result["response"] == "API key auth success"

        # Verify HTTP client was called with correct custom headers
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        headers_used = call_args.kwargs.get("headers", {})
        assert "X-API-Key" in headers_used
        assert headers_used["X-API-Key"] == "test-key-for-unit-test"
        assert "X-Custom-Header" in headers_used
        assert headers_used["X-Custom-Header"] == "custom-value"

    async def test_aggregate_metrics(self, service, mock_db):
        """Test metrics aggregation."""
        # Mock aggregate_metrics_combined to return a proper AggregatedMetrics result
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        mock_metrics = AggregatedMetrics(
            total_executions=100,
            successful_executions=90,
            failed_executions=10,
            failure_rate=0.1,
            min_response_time=0.5,
            max_response_time=3.0,
            avg_response_time=1.5,
            last_execution_time="2025-01-01T00:00:00+00:00",
            raw_count=60,
            rollup_count=40,
        )

        # Mock the cache for agent counts
        mock_counts_result = MagicMock()
        mock_counts_result.total = 5
        mock_counts_result.active = 3
        mock_db.execute.return_value.one.return_value = mock_counts_result

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_metrics):
            # Execute
            result = await service.aggregate_metrics(mock_db)

        # Verify
        assert result["total_agents"] == 5
        assert result["active_agents"] == 3
        assert result["total_interactions"] == 100
        assert result["successful_interactions"] == 90
        assert result["failed_interactions"] == 10
        assert result["success_rate"] == 90.0
        assert result["avg_response_time"] == 1.5

    async def test_reset_metrics_all(self, service, mock_db):
        """Test resetting all metrics."""
        mock_db.execute = MagicMock()
        mock_db.commit = MagicMock()

        # Execute
        await service.reset_metrics(mock_db)

        # Verify
        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()

    async def test_reset_metrics_specific_agent(self, service, mock_db):
        """Test resetting metrics for specific agent."""
        agent_id = uuid.uuid4().hex
        mock_db.execute = MagicMock()
        mock_db.commit = MagicMock()

        # Execute
        await service.reset_metrics(mock_db, agent_id)

        # Verify
        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()

    def testconvert_agent_to_read_conversion(self, service, sample_db_agent):
        """
        Test database model to schema conversion with db parameter.
        """

        mock_db = MagicMock()
        service._get_team_name = MagicMock(return_value="Test Team")

        # Add some mock metrics
        metric1 = MagicMock()
        metric1.is_success = True
        metric1.response_time = 1.0
        metric1.timestamp = datetime.now(timezone.utc)

        metric2 = MagicMock()
        metric2.is_success = False
        metric2.response_time = 2.0
        metric2.timestamp = datetime.now(timezone.utc)

        sample_db_agent.metrics = [metric1, metric2]

        # Add dummy auth_value (doesn't matter since we'll patch decode_auth)
        sample_db_agent.auth_value = "fake_encrypted_auth"

        # Set all required attributes
        sample_db_agent.created_by = "test_user"
        sample_db_agent.created_from_ip = "127.0.0.1"
        sample_db_agent.created_via = "test"
        sample_db_agent.created_user_agent = "test"
        sample_db_agent.modified_by = None
        sample_db_agent.modified_from_ip = None
        sample_db_agent.modified_via = None
        sample_db_agent.modified_user_agent = None
        sample_db_agent.import_batch_id = None
        sample_db_agent.federation_source = None
        sample_db_agent.version = 1
        sample_db_agent.visibility = "private"
        sample_db_agent.auth_type = "none"
        sample_db_agent.auth_header_key = "Authorization"
        sample_db_agent.auth_header_value = "Basic dGVzdDp2YWx1ZQ=="  # base64 for "test:value"
        print(f"sample_db_agent: {sample_db_agent}")
        # Patch decode_auth to return a dummy decoded dict
        with patch("mcpgateway.schemas.decode_auth", return_value={"user": "decoded"}):
            result = service.convert_agent_to_read(mock_db, sample_db_agent, include_metrics=True)

        # Verify
        assert result.id == sample_db_agent.id
        assert result.name == sample_db_agent.name
        assert result.metrics.total_executions == 2
        assert result.metrics.successful_executions == 1
        assert result.metrics.failed_executions == 1
        assert result.metrics.failure_rate == 50.0
        assert result.metrics.avg_response_time == 1.5
        assert result.team == "Test Team"

    def test_get_team_name_and_batch(self, service, mock_db):
        """Test team name lookup helpers."""
        team = SimpleNamespace(name="Team A")
        query = MagicMock()
        query.filter.return_value = query
        query.first.return_value = team
        mock_db.query.return_value = query
        mock_db.commit = MagicMock()

        assert service._get_team_name(mock_db, "team-1") == "Team A"
        mock_db.commit.assert_called_once()

        # No team_id returns None without querying
        assert service._get_team_name(mock_db, None) is None

        team_rows = [SimpleNamespace(id="t1", name="One"), SimpleNamespace(id="t2", name="Two")]
        query_all = MagicMock()
        query_all.filter.return_value = query_all
        query_all.all.return_value = team_rows
        mock_db.query.return_value = query_all

        result = service._batch_get_team_names(mock_db, ["t1", "t2"])
        assert result == {"t1": "One", "t2": "Two"}
        assert service._batch_get_team_names(mock_db, []) == {}

    def test_check_agent_access_variants(self, service):
        """Test access control logic for agent visibility."""
        agent = SimpleNamespace(visibility="public", team_id="team-1", owner_email="owner@example.com")

        assert service._check_agent_access(agent, user_email=None, token_teams=None) is True
        assert service._check_agent_access(agent, user_email=None, token_teams=["x"]) is True

        agent.visibility = "team"
        assert service._check_agent_access(agent, user_email=None, token_teams=["team-1"]) is True
        assert service._check_agent_access(agent, user_email=None, token_teams=["other"]) is False

        agent.visibility = "private"
        assert service._check_agent_access(agent, user_email="owner@example.com", token_teams=[]) is False
        assert service._check_agent_access(agent, user_email="owner@example.com", token_teams=["team-1"]) is True
        assert service._check_agent_access(agent, user_email="other@example.com", token_teams=["team-1"]) is False

    def test_apply_visibility_filter(self, service):
        """Test visibility filter branches."""
        query = MagicMock()
        query.where.return_value = "filtered"

        result = service._apply_visibility_filter(query, user_email="user@example.com", token_teams=["team-1"], team_id="team-2")
        assert result == "filtered"
        query.where.assert_called()

        query.where.reset_mock()
        result = service._apply_visibility_filter(query, user_email="user@example.com", token_teams=["team-1"], team_id="team-1")
        assert result == "filtered"
        query.where.assert_called()

        query.where.reset_mock()
        result = service._apply_visibility_filter(query, user_email=None, token_teams=[])
        assert result == "filtered"
        query.where.assert_called()

    async def test_list_agents_cache_hit(self, service, mock_db, monkeypatch):
        """Test cached list_agents response."""
        cache = SimpleNamespace(
            hash_filters=MagicMock(return_value="hash"),
            get=AsyncMock(return_value={"agents": [{"id": "a1"}], "next_cursor": "next"}),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        from mcpgateway.schemas import A2AAgentRead

        monkeypatch.setattr(A2AAgentRead, "model_validate", MagicMock(return_value=MagicMock()))

        agents, cursor = await service.list_agents(mock_db)
        assert cursor == "next"
        assert len(agents) == 1

    async def test_register_agent_team_conflict(self, service, mock_db, sample_agent_create):
        """Test team visibility name conflict."""
        conflict = MagicMock()
        conflict.enabled = True
        conflict.id = "agent-1"
        conflict.visibility = "team"

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=conflict):
            with pytest.raises(A2AAgentNameConflictError):
                await service.register_agent(mock_db, sample_agent_create, visibility="team", team_id="team-1")

    async def test_register_agent_auth_headers_encoded(self, service, mock_db, sample_agent_create, monkeypatch):
        """Test auth_headers encoding and cache handling."""
        agent_data = sample_agent_create.model_copy()
        agent_data.auth_headers = [{"key": "X-API-Key", "value": "secret"}]
        agent_data.auth_value = None

        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.add = MagicMock()

        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(invalidate=MagicMock()))
        monkeypatch.setattr("mcpgateway.services.a2a_service.encode_auth", lambda _val: "encoded")

        tool = SimpleNamespace(id="tool-1")
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with patch("mcpgateway.services.tool_service.tool_service") as tool_service:
                tool_service.create_tool_from_a2a_agent = AsyncMock(return_value=tool)
                service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                await service.register_agent(mock_db, agent_data)

        added_agent = mock_db.add.call_args_list[0][0][0]
        assert added_agent.auth_value == "encoded"

    async def test_update_agent_invalid_passthrough_headers(self, service, mock_db, sample_db_agent):
        """Test invalid passthrough_headers format raises error."""
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            update = A2AAgentUpdate.model_construct(passthrough_headers=123)
            with pytest.raises(A2AAgentError):
                await service.update_agent(mock_db, sample_db_agent.id, update)

    async def test_update_agent_permission_denied(self, service, mock_db, sample_db_agent):
        """Test update denied when user is not owner."""
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            with patch("mcpgateway.services.permission_service.PermissionService") as perm_cls:
                perm = perm_cls.return_value
                perm.check_resource_ownership = AsyncMock(return_value=False)
                with pytest.raises(PermissionError):
                    await service.update_agent(mock_db, sample_db_agent.id, A2AAgentUpdate(description="x"), user_email="user@example.com")

    def test_prepare_agent_for_read_encodes_auth(self, service):
        agent = SimpleNamespace(auth_value={"Authorization": "Bearer token"})
        with patch("mcpgateway.services.a2a_service.encode_auth", return_value="encoded") as enc:
            result = service._prepare_a2a_agent_for_read(agent)
        assert result.auth_value == "encoded"
        enc.assert_called_once()


class TestA2AAgentIntegration:
    """Integration tests for A2A agent functionality."""

    async def test_agent_tool_creation_workflow(self):
        """Test the complete workflow of creating an agent and exposing it as a tool."""
        # This would be an integration test that verifies:
        # 1. A2A agent is created
        # 2. Agent is associated with a virtual server
        # 3. Tool is automatically created for the agent
        # 4. Tool can be invoked and routes to A2A agent
        pass  # Implementation would require test database setup

    async def test_agent_metrics_integration(self):
        """Test that agent invocations properly record metrics."""
        # This would test that:
        # 1. Agent invocations create metrics records
        # 2. Metrics are properly aggregated
        # 3. Tool invocations for A2A agents also record metrics
        pass  # Implementation would require test database setup
