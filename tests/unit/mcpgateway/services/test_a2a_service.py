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
from mcpgateway.schemas import A2AAgentCreate, A2AAgentRead, A2AAgentUpdate
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

        # team_id path where owner access is NOT added (no user_email)
        query.where.reset_mock()
        result = service._apply_visibility_filter(query, user_email=None, token_teams=["team-1"], team_id="team-1")
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

    async def test_register_agent_team_success_no_conflict(self, service, mock_db, sample_agent_create, monkeypatch):
        """Team visibility registration succeeds when no conflict exists."""
        agent_data = sample_agent_create.model_copy()

        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.add = MagicMock()

        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(invalidate=MagicMock()))

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with patch("mcpgateway.services.tool_service.tool_service") as tool_service:
                tool_service.create_tool_from_a2a_agent = AsyncMock(return_value=None)
                service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                await service.register_agent(mock_db, agent_data, visibility="team", team_id="team-1")

        added_agent = mock_db.add.call_args_list[0][0][0]
        assert added_agent.visibility == "team"
        assert added_agent.team_id == "team-1"

    async def test_register_agent_private_visibility_skips_conflict_checks(self, service, mock_db, sample_agent_create, monkeypatch):
        """Private visibility skips public/team conflict checks."""
        agent_data = sample_agent_create.model_copy()

        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.add = MagicMock()

        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(invalidate=MagicMock()))

        with patch("mcpgateway.services.a2a_service.get_for_update") as mock_get:
            with patch("mcpgateway.services.tool_service.tool_service") as tool_service:
                tool_service.create_tool_from_a2a_agent = AsyncMock(return_value=None)
                service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                await service.register_agent(mock_db, agent_data, visibility="private")

        mock_get.assert_not_called()

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

    async def test_update_agent_permission_allowed(self, service, mock_db, sample_db_agent, monkeypatch):
        """Owner passes PermissionService check and update proceeds."""
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            with patch("mcpgateway.services.permission_service.PermissionService") as perm_cls:
                perm_cls.return_value.check_resource_ownership = AsyncMock(return_value=True)

                mock_db.commit = MagicMock()
                mock_db.refresh = MagicMock()

                dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
                monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
                monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

                with patch("mcpgateway.services.tool_service.tool_service") as ts:
                    ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)
                    service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                    await service.update_agent(mock_db, sample_db_agent.id, A2AAgentUpdate(description="x"), user_email="user@example.com")

    def test_prepare_agent_for_read_encodes_auth(self, service):
        agent = SimpleNamespace(auth_value={"Authorization": "Bearer token"})
        with patch("mcpgateway.services.a2a_service.encode_auth", return_value="encoded") as enc:
            result = service._prepare_a2a_agent_for_read(agent)
        assert result.auth_value == "encoded"
        enc.assert_called_once()

    def test_prepare_agent_for_read_noop_for_string_auth(self, service):
        agent = SimpleNamespace(auth_value="already-encoded")
        with patch("mcpgateway.services.a2a_service.encode_auth") as enc:
            result = service._prepare_a2a_agent_for_read(agent)
        assert result.auth_value == "already-encoded"
        enc.assert_not_called()


# ---------------------------------------------------------------------------
# Batch 2: Edge-case and branch-coverage tests
# ---------------------------------------------------------------------------


class TestNameConflictErrorBranches:
    """Cover the inactive-conflict message branch in A2AAgentNameConflictError."""

    def test_inactive_conflict_message(self):
        err = A2AAgentNameConflictError("slug", is_active=False, agent_id="a-1")
        assert "inactive" in str(err)
        assert "a-1" in str(err)

    def test_active_conflict_message(self):
        err = A2AAgentNameConflictError("slug", is_active=True)
        assert "inactive" not in str(err)

    def test_team_visibility_conflict_message(self):
        err = A2AAgentNameConflictError("slug", visibility="team")
        assert "Team" in str(err)


class TestInitializeShutdownBranches:
    """Cover already-initialized / already-shutdown branches."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    async def test_double_initialize(self, service):
        await service.initialize()
        assert service._initialized
        await service.initialize()  # no-op second call
        assert service._initialized

    async def test_shutdown_when_not_initialized(self, service):
        assert not service._initialized
        await service.shutdown()  # no-op
        assert not service._initialized


class TestGetAgentEdgeCases:
    """Cover inactive-agent filter and access check branches in get_agent."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_get_agent_inactive_excluded(self, service, mock_db):
        """Inactive agent with include_inactive=False raises NotFound."""
        agent = SimpleNamespace(id="a1", enabled=False, visibility="public", team_id=None, owner_email=None)
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent

        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(mock_db, "a1", include_inactive=False)

    async def test_get_agent_access_denied(self, service, mock_db):
        """Private agent not accessible with wrong teams → NotFound (not 403)."""
        agent = SimpleNamespace(id="a1", enabled=True, visibility="private", team_id="t1", owner_email="other@x.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent

        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(mock_db, "a1", user_email="me@x.com", token_teams=[])

    async def test_get_agent_by_name_not_found(self, service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(A2AAgentNotFoundError, match="not found with name"):
            await service.get_agent_by_name(mock_db, "no-such-agent")


class TestSetAgentStateEdgeCases:
    """Cover set_agent_state not-found and permission-denied branches."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_set_state_not_found(self, service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(A2AAgentNotFoundError):
            await service.set_agent_state(mock_db, "no-id", activate=True)

    async def test_set_state_permission_denied(self, service, mock_db):
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, owner_email="owner@x.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent

        with patch("mcpgateway.services.permission_service.PermissionService") as perm_cls:
            perm_cls.return_value.check_resource_ownership = AsyncMock(return_value=False)
            with pytest.raises(PermissionError):
                await service.set_agent_state(mock_db, "a1", activate=False, user_email="hacker@x.com")

    async def test_set_state_permission_allowed(self, service, mock_db, monkeypatch):
        """Owner can toggle activation when PermissionService allows it."""
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, owner_email="owner@x.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)

        with patch("mcpgateway.services.permission_service.PermissionService") as perm_cls:
            perm_cls.return_value.check_resource_ownership = AsyncMock(return_value=True)
            await service.set_agent_state(mock_db, "a1", activate=False, user_email="owner@x.com")

        assert agent.enabled is False

    async def test_set_state_with_reachable(self, service, mock_db):
        """Setting reachable flag together with activation."""
        agent = SimpleNamespace(id="a1", enabled=False, name="ag", reachable=False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        await service.set_agent_state(mock_db, "a1", activate=True, reachable=True)
        assert agent.enabled is True
        assert agent.reachable is True


class TestDeleteAgentEdgeCases:
    """Cover permission-denied branch in delete_agent."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_delete_permission_denied(self, service, mock_db):
        agent = SimpleNamespace(id="a1", name="ag", enabled=True, owner_email="owner@x.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent

        with patch("mcpgateway.services.permission_service.PermissionService") as perm_cls:
            perm_cls.return_value.check_resource_ownership = AsyncMock(return_value=False)
            with pytest.raises(PermissionError):
                await service.delete_agent(mock_db, "a1", user_email="hacker@x.com")

    async def test_delete_permission_allowed(self, service, mock_db, monkeypatch):
        """Owner can delete agent when PermissionService allows it."""
        agent = SimpleNamespace(id="a1", name="ag", enabled=True, owner_email="owner@x.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()

        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

        with patch("mcpgateway.services.permission_service.PermissionService") as perm_cls:
            perm_cls.return_value.check_resource_ownership = AsyncMock(return_value=True)
            with patch("mcpgateway.services.tool_service.tool_service") as tool_service:
                tool_service.delete_tool_from_a2a_agent = AsyncMock(return_value=None)
                await service.delete_agent(mock_db, "a1", user_email="owner@x.com")

        mock_db.delete.assert_called_once_with(agent)


class TestRegisterAgentEdgeCases:
    """Cover exception handling and cache error branches in register_agent."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def agent_data(self):
        return A2AAgentCreate(
            name="test-agent", endpoint_url="https://api.example.com/agent",
            agent_type="custom", protocol_version="1.0", capabilities={}, config={},
        )

    async def test_register_integrity_error(self, service, mock_db, agent_data, monkeypatch):
        """IntegrityError from DB is re-raised."""
        from sqlalchemy.exc import IntegrityError as IE

        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock(side_effect=IE("dup", None, Exception()))
        mock_db.rollback = MagicMock()

        with pytest.raises(IE):
            await service.register_agent(mock_db, agent_data)

    async def test_register_generic_exception(self, service, mock_db, agent_data, monkeypatch):
        """Generic exception wraps in A2AAgentError."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        mock_db.add = MagicMock(side_effect=RuntimeError("boom"))
        mock_db.rollback = MagicMock()

        with pytest.raises(A2AAgentError, match="Failed to register"):
            await service.register_agent(mock_db, agent_data)

    async def test_register_cache_invalidation_failure(self, service, mock_db, agent_data, monkeypatch):
        """Cache error after successful commit doesn't fail registration."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        # Cache invalidation raises
        monkeypatch.setattr("mcpgateway.services.a2a_service.a2a_stats_cache", SimpleNamespace(invalidate=MagicMock(side_effect=Exception("cache down"))))

        service.convert_agent_to_read = MagicMock(return_value=MagicMock())
        # Should succeed despite cache error
        await service.register_agent(mock_db, agent_data)
        service.convert_agent_to_read.assert_called_once()

    async def test_register_tool_creation_fails(self, service, mock_db, agent_data, monkeypatch):
        """Tool creation failure logs warning but agent registration succeeds."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        # Cache invalidation succeeds
        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(invalidate=MagicMock()))

        # Tool creation raises
        with patch("mcpgateway.services.tool_service.tool_service") as ts:
            ts.create_tool_from_a2a_agent = AsyncMock(side_effect=Exception("tool fail"))
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())
            await service.register_agent(mock_db, agent_data)

        service.convert_agent_to_read.assert_called_once()

    async def test_register_query_param_disabled(self, service, mock_db, monkeypatch):
        """Query param auth disabled raises ValueError."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = False
            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent", slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom", protocol_version="1.0",
                capabilities={}, config={}, tags=[], auth_type="query_param",
                auth_query_param_key="key", auth_query_param_value="val",
            )
            with pytest.raises(ValueError, match="disabled"):
                await service.register_agent(mock_db, agent_data)

    async def test_register_query_param_host_not_allowed(self, service, mock_db, monkeypatch):
        """Query param auth host not in allowlist raises ValueError."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = ["safe.host.com"]
            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent", slug="qp-agent",
                endpoint_url="https://bad.host.com/agent",
                agent_type="custom", protocol_version="1.0",
                capabilities={}, config={}, tags=[], auth_type="query_param",
                auth_query_param_key="key", auth_query_param_value="val",
            )
            with pytest.raises(ValueError, match="not in the allowed"):
                await service.register_agent(mock_db, agent_data)

    async def test_register_query_param_secretstr_value(self, service, mock_db, monkeypatch):
        """Query param with SecretStr-typed value correctly extracts via get_secret_value."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        # Cache and tool mocks
        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(invalidate=MagicMock()))

        # SecretStr mock
        secret_val = MagicMock()
        secret_val.get_secret_value.return_value = "the-secret"

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = []

            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent", slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom", protocol_version="1.0",
                capabilities={}, config={}, tags=[], auth_type="query_param",
                auth_query_param_key="api_key", auth_query_param_value=secret_val,
            )
            with patch("mcpgateway.services.tool_service.tool_service") as ts:
                ts.create_tool_from_a2a_agent = AsyncMock(return_value=None)
                service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                await service.register_agent(mock_db, agent_data)

        added_agent = mock_db.add.call_args[0][0]
        assert added_agent.auth_type == "query_param"
        assert added_agent.auth_query_params is not None
        assert added_agent.auth_value is None

    async def test_register_query_param_non_secret_value_uses_str(self, service, mock_db, monkeypatch):
        """Query param with non-SecretStr value uses str() conversion."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(invalidate=MagicMock()))
        monkeypatch.setattr("mcpgateway.services.a2a_service.encode_auth", lambda _val: "encrypted")

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = []

            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent", slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom", protocol_version="1.0",
                capabilities={}, config={}, tags=[], auth_type="query_param",
                auth_query_param_key="api_key", auth_query_param_value=123,
            )
            with patch("mcpgateway.services.tool_service.tool_service") as ts:
                ts.create_tool_from_a2a_agent = AsyncMock(return_value=None)
                service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                await service.register_agent(mock_db, agent_data)

        added_agent = mock_db.add.call_args[0][0]
        assert added_agent.auth_query_params == {"api_key": "encrypted"}

    async def test_register_query_param_missing_key_or_value_skips_encryption(self, service, mock_db, monkeypatch):
        """Missing key/value skips auth_query_params encryption and continues."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(invalidate=MagicMock()))

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = []

            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent", slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom", protocol_version="1.0",
                capabilities={}, config={}, tags=[], auth_type="query_param",
                auth_query_param_key=None, auth_query_param_value=None,
            )
            with patch("mcpgateway.services.tool_service.tool_service") as ts:
                ts.create_tool_from_a2a_agent = AsyncMock(return_value=None)
                service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                await service.register_agent(mock_db, agent_data)

        added_agent = mock_db.add.call_args[0][0]
        assert added_agent.auth_query_params is None


class TestAgentCardDiscovery:
    """Cover Agent Card discovery helpers and extended-card auth behavior."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_discover_agent_card_merges_extended_card(self, mock_get_client, service):
        """When base card advertises authenticated extended card, merge its capabilities."""

        def _response(status_code: int, payload: dict):
            response = MagicMock()
            response.status_code = status_code
            response.json = MagicMock(return_value=payload)
            return response

        async def _fake_get(url: str, headers=None):  # noqa: ANN001
            if url.endswith("/extendedAgentCard") or url.endswith("/v1/extendedAgentCard"):
                return _response(
                    200,
                    {
                        "name": "agent",
                        "url": "https://agent.example.com",
                        "capabilities": {"pushNotifications": True},
                    },
                )
            if url.endswith("/.well-known/agent-card.json"):
                return _response(
                    200,
                    {
                        "name": "agent",
                        "url": "https://agent.example.com",
                        "supportsAuthenticatedExtendedCard": True,
                        "capabilities": {"streaming": False},
                    },
                )
            return _response(404, {})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_fake_get)
        mock_get_client.return_value = mock_client

        discovered = await service._discover_agent_card("https://agent.example.com/base/path", {"Authorization": "Bearer abc"})
        assert discovered is not None
        assert discovered["capabilities"]["streaming"] is False
        assert discovered["capabilities"]["pushNotifications"] is True

    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_discover_agent_card_falls_back_to_extended_card(self, mock_get_client, service):
        """If only extended card exists and auth is present, discovery should still succeed."""

        def _response(status_code: int, payload: dict):
            response = MagicMock()
            response.status_code = status_code
            response.json = MagicMock(return_value=payload)
            return response

        async def _fake_get(url: str, headers=None):  # noqa: ANN001
            if url.endswith("/extendedAgentCard") or url.endswith("/v1/extendedAgentCard"):
                return _response(200, {"name": "agent", "url": "https://agent.example.com"})
            return _response(404, {})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_fake_get)
        mock_get_client.return_value = mock_client

        discovered = await service._discover_agent_card("https://agent.example.com/base/path", {"Authorization": "Bearer abc"})
        assert discovered is not None
        assert discovered["name"] == "agent"

    def test_build_agent_card_candidates_include_extended(self, service):
        """Extended discovery candidates include `/extendedAgentCard` variants."""
        candidates = service._build_agent_card_candidates("https://agent.example.com/base/path", include_extended=True)
        assert any(candidate.endswith("/extendedAgentCard") for candidate in candidates)


class TestListAgentsAdvanced:
    """Cover list_agents branches: user_email DB lookup, page-based, cache write, validation skip."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_list_with_user_email_db_lookup(self, service, mock_db, monkeypatch):
        """user_email provided without token_teams triggers DB team lookup."""
        agent = SimpleNamespace(id="a1", team_id=None, visibility="public")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[])
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            # Cache miss
            cache = SimpleNamespace(hash_filters=MagicMock(return_value="h"), get=AsyncMock(return_value=None), set=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

            result, cursor = await service.list_agents(mock_db, user_email="user@x.com")
            tm_cls.return_value.get_user_teams.assert_awaited_once()

    async def test_list_with_token_teams(self, service, mock_db, monkeypatch):
        """token_teams provided directly — no DB team lookup."""
        agent = SimpleNamespace(id="a1", team_id="t1", visibility="team")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        mock_db.commit = MagicMock()

        service.convert_agent_to_read = MagicMock(return_value=MagicMock())
        cache = SimpleNamespace(hash_filters=MagicMock(return_value="h"), get=AsyncMock(return_value=None), set=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        result, cursor = await service.list_agents(mock_db, token_teams=["t1"])
        assert len(result) == 1

    async def test_list_page_based_pagination(self, service, mock_db, monkeypatch):
        """Page-based pagination returns dict format."""
        agent = SimpleNamespace(id="a1", team_id=None, visibility="public")

        # Mock unified_paginate to return page-based format
        monkeypatch.setattr("mcpgateway.services.a2a_service.unified_paginate", AsyncMock(return_value={
            "data": [agent], "pagination": {"page": 1, "total": 1}, "links": {},
        }))
        mock_db.execute.return_value.all.return_value = []
        mock_db.commit = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        result = await service.list_agents(mock_db, page=1, per_page=10)
        assert isinstance(result, dict)
        assert "data" in result
        assert "pagination" in result

    async def test_list_validation_error_skips_agent(self, service, mock_db, monkeypatch):
        """ValidationError during conversion skips agent instead of failing."""
        from pydantic import ValidationError

        agent = SimpleNamespace(id="bad", team_id=None, name="bad-agent", visibility="public")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        mock_db.commit = MagicMock()

        service.convert_agent_to_read = MagicMock(side_effect=ValidationError.from_exception_data("test", []))
        cache = SimpleNamespace(hash_filters=MagicMock(return_value="h"), get=AsyncMock(return_value=None), set=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        result, cursor = await service.list_agents(mock_db)
        assert result == []  # skipped bad agent

    async def test_list_with_visibility_filter(self, service, mock_db, monkeypatch):
        """Visibility filter is applied."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        mock_db.commit = MagicMock()

        cache = SimpleNamespace(hash_filters=MagicMock(return_value="h"), get=AsyncMock(return_value=None), set=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        result, cursor = await service.list_agents(mock_db, visibility="private", user_email="u@x.com", token_teams=["t1"])
        assert result == []

    async def test_list_with_team_names(self, service, mock_db, monkeypatch):
        """Team names are fetched for agents with team_id."""
        team_row = SimpleNamespace(id="t1", name="Alpha")
        agent = SimpleNamespace(id="a1", team_id="t1", visibility="team")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        # For team lookup: second execute call returns team rows
        mock_db.execute.return_value.all.return_value = [team_row]
        mock_db.commit = MagicMock()

        service.convert_agent_to_read = MagicMock(return_value=MagicMock())
        cache = SimpleNamespace(hash_filters=MagicMock(return_value="h"), get=AsyncMock(return_value=None), set=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        result, cursor = await service.list_agents(mock_db)
        assert len(result) == 1

    async def test_list_cache_write(self, service, mock_db, monkeypatch):
        """Cache write occurs for admin-level (no user/token) cursor-based results."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        mock_db.execute.return_value.all.return_value = []
        mock_db.commit = MagicMock()

        cache = SimpleNamespace(hash_filters=MagicMock(return_value="h"), get=AsyncMock(return_value=None), set=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        await service.list_agents(mock_db)
        cache.set.assert_awaited_once()


class TestListAgentsForUser:
    """Cover the deprecated list_agents_for_user method."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_string_user_info(self, service, mock_db):
        """String user_info is treated as email directly."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[])
            result = await service.list_agents_for_user(mock_db, "user@x.com")

        assert result == []

    async def test_dict_user_info(self, service, mock_db):
        """Dict user_info extracts email from 'email' key."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[])
            result = await service.list_agents_for_user(mock_db, {"email": "user@x.com"})

        assert result == []

    async def test_with_accessible_teams_filters_team_agents(self, service, mock_db):
        """When user has teams, team visibility agents are included in access conditions."""
        team = SimpleNamespace(id="t1", name="Alpha")
        agent = SimpleNamespace(id="a1", team_id="t1", name="ag", visibility="team", owner_email="user@x.com")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[team])
            service._batch_get_team_names = MagicMock(return_value={"t1": "Alpha"})
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())
            result = await service.list_agents_for_user(mock_db, {"email": "user@x.com"})

        assert len(result) == 1

    async def test_with_team_id_no_access(self, service, mock_db):
        """Requesting team user doesn't belong to returns empty."""
        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[])
            result = await service.list_agents_for_user(mock_db, {"email": "user@x.com"}, team_id="other-team")

        assert result == []

    async def test_with_team_id_has_access(self, service, mock_db):
        """Requesting team user belongs to returns filtered agents."""
        team = SimpleNamespace(id="t1", name="Alpha")
        agent = SimpleNamespace(id="a1", team_id="t1", name="ag", visibility="team", owner_email="user@x.com")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[team])
            service._batch_get_team_names = MagicMock(return_value={"t1": "Alpha"})
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())
            result = await service.list_agents_for_user(mock_db, {"email": "user@x.com"}, team_id="t1")

        assert len(result) == 1

    async def test_with_visibility_filter(self, service, mock_db):
        """Visibility parameter further filters results."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[])
            result = await service.list_agents_for_user(mock_db, {"email": "u@x.com"}, visibility="private")

        assert result == []

    async def test_validation_error_skips_agent(self, service, mock_db):
        """ValidationError during conversion skips agent in list."""
        from pydantic import ValidationError

        agent = SimpleNamespace(id="bad", team_id=None, name="bad", visibility="public", owner_email="u@x.com")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.a2a_service.TeamManagementService") as tm_cls:
            tm_cls.return_value.get_user_teams = AsyncMock(return_value=[])
            service._batch_get_team_names = MagicMock(return_value={})
            service.convert_agent_to_read = MagicMock(side_effect=ValidationError.from_exception_data("test", []))
            result = await service.list_agents_for_user(mock_db, "u@x.com")

        assert result == []


class TestUpdateAgentAdvanced:
    """Cover update_agent branches: name conflict, passthrough, query_param, metadata."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def _make_agent(self, **overrides):
        defaults = dict(
            id="a1", name="ag", slug="ag", endpoint_url="https://example.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            enabled=True, version=1, visibility="public", team_id=None,
            owner_email=None, passthrough_headers=None, oauth_config=None,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    async def test_name_conflict_public(self, service, mock_db, monkeypatch):
        """Renaming to existing public slug raises NameConflictError."""
        agent = self._make_agent()
        conflict = SimpleNamespace(enabled=True, id="other", visibility="public")

        with patch("mcpgateway.services.a2a_service.get_for_update", side_effect=[agent, conflict]):
            update = A2AAgentUpdate(name="new-name")
            with pytest.raises(A2AAgentNameConflictError):
                await service.update_agent(mock_db, "a1", update)

    async def test_name_conflict_team(self, service, mock_db, monkeypatch):
        """Renaming to existing team slug raises NameConflictError."""
        agent = self._make_agent(visibility="team", team_id="t1")
        conflict = SimpleNamespace(enabled=True, id="other", visibility="team")

        with patch("mcpgateway.services.a2a_service.get_for_update", side_effect=[agent, conflict]):
            update = A2AAgentUpdate(name="new-name")
            with pytest.raises(A2AAgentNameConflictError):
                await service.update_agent(mock_db, "a1", update)

    async def test_rename_success_updates_slug(self, service, mock_db, monkeypatch):
        """Successful rename updates slug when no conflict exists."""
        agent = self._make_agent(name="old", slug="old", visibility="public")

        # First get_for_update returns the agent row; second returns no conflict
        with patch("mcpgateway.services.a2a_service.get_for_update", side_effect=[agent, None]):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with patch("mcpgateway.services.tool_service.tool_service") as ts:
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)
                await service.update_agent(mock_db, "a1", A2AAgentUpdate(name="new-name"))

        assert agent.slug == "new-name"

    async def test_passthrough_headers_list(self, service, mock_db, monkeypatch):
        """List passthrough_headers is cleaned and set."""
        agent = self._make_agent()
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())
            update = A2AAgentUpdate.model_construct(passthrough_headers=["X-Foo", " ", "X-Bar"])
            await service.update_agent(mock_db, "a1", update)
        assert agent.passthrough_headers == ["X-Foo", "X-Bar"]

    async def test_passthrough_headers_string(self, service, mock_db, monkeypatch):
        """Comma-separated string passthrough_headers is parsed."""
        agent = self._make_agent()
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())
            update = A2AAgentUpdate.model_construct(passthrough_headers="X-Foo, X-Bar")
            await service.update_agent(mock_db, "a1", update)
        assert agent.passthrough_headers == ["X-Foo", "X-Bar"]

    async def test_passthrough_headers_none(self, service, mock_db, monkeypatch):
        """None passthrough_headers clears it."""
        agent = self._make_agent(passthrough_headers=["X-Old"])
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())
            update = A2AAgentUpdate.model_construct(passthrough_headers=None)
            await service.update_agent(mock_db, "a1", update)
        assert agent.passthrough_headers is None

    async def test_metadata_updates(self, service, mock_db, monkeypatch):
        """Modified metadata fields are set on agent."""
        agent = self._make_agent()
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())
            update = A2AAgentUpdate(description="new desc")
            await service.update_agent(
                mock_db, "a1", update,
                modified_by="user", modified_from_ip="1.2.3.4",
                modified_via="api", modified_user_agent="test/1.0",
            )
        assert agent.modified_by == "user"
        assert agent.modified_from_ip == "1.2.3.4"
        assert agent.modified_via == "api"
        assert agent.modified_user_agent == "test/1.0"

    async def test_tool_sync_error_doesnt_fail(self, service, mock_db, monkeypatch):
        """Tool sync failure logs warning but agent update succeeds."""
        agent = self._make_agent()
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with patch("mcpgateway.services.tool_service.tool_service") as ts:
                ts.update_tool_from_a2a_agent = AsyncMock(side_effect=Exception("sync fail"))
                update = A2AAgentUpdate(description="updated")
                result = await service.update_agent(mock_db, "a1", update)

        assert result is not None

    async def test_integrity_error(self, service, mock_db, monkeypatch):
        """IntegrityError from DB is re-raised."""
        from sqlalchemy.exc import IntegrityError as IE

        agent = self._make_agent()
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock(side_effect=IE("dup", None, Exception()))
            mock_db.rollback = MagicMock()
            update = A2AAgentUpdate(description="x")
            with pytest.raises(IE):
                await service.update_agent(mock_db, "a1", update)

    async def test_queryparam_switching_disabled_grandfather(self, service, mock_db, monkeypatch):
        """Switching to query_param when disabled raises ValueError."""
        agent = self._make_agent(auth_type="bearer")
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with patch("mcpgateway.config.settings") as mock_settings:
                mock_settings.insecure_allow_queryparam_auth = False
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                update = A2AAgentUpdate.model_construct(
                    auth_type="query_param", auth_query_param_key="k", auth_query_param_value="v",
                )
                with pytest.raises(A2AAgentError, match="Failed to update"):
                    await service.update_agent(mock_db, "a1", update)

    async def test_queryparam_host_not_allowed_on_update(self, service, mock_db, monkeypatch):
        """Host allowlist is enforced when switching to query_param."""
        agent = self._make_agent(auth_type="bearer", endpoint_url="https://bad.host.com/agent")
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with patch("mcpgateway.config.settings") as mock_settings:
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = ["safe.host.com"]
                update = A2AAgentUpdate.model_construct(
                    auth_type="query_param", auth_query_param_key="k", auth_query_param_value="v",
                )
                with pytest.raises(A2AAgentError, match="Failed to update"):
                    await service.update_agent(mock_db, "a1", update)


class TestInvokeAgentEdgeCases:
    """Cover invoke_agent branches: not-found, access denied, auth paths, exceptions."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_invoke_name_lookup_not_found(self, service, mock_db):
        """Name lookup returns None → A2AAgentNotFoundError."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(A2AAgentNotFoundError, match="not found with name"):
            await service.invoke_agent(mock_db, "no-agent", {})

    async def test_invoke_get_for_update_not_found(self, service, mock_db, monkeypatch):
        """get_for_update returns None → A2AAgentNotFoundError."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = "some-id"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)
        with pytest.raises(A2AAgentNotFoundError, match="not found with name"):
            await service.invoke_agent(mock_db, "missing-agent", {})

    async def test_invoke_access_denied(self, service, mock_db, monkeypatch):
        """Private agent inaccessible → A2AAgentNotFoundError."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        agent = SimpleNamespace(
            id="a1", name="secret", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="private", team_id="t1", owner_email="other@x.com",
            agent_type="generic", protocol_version="1.0",
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)

        with pytest.raises(A2AAgentNotFoundError):
            await service.invoke_agent(mock_db, "secret", {}, user_email="me@x.com", token_teams=[])

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_dict_auth_value(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Dict auth_value is converted to string headers."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type="authheaders", auth_value={"X-Key": "val"},
            auth_query_params=None, visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        await service.invoke_agent(mock_db, "ag", {"method": "message/send", "params": {}})
        headers_used = mock_client.post.call_args.kwargs["headers"]
        assert headers_used.get("X-Key") == "val"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_custom_a2a_format(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Non-generic agent type sends custom A2A format."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/custom",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="custom", protocol_version="2.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        await service.invoke_agent(mock_db, "ag", {"test": "data"}, interaction_type="query")
        post_data = mock_client.post.call_args.kwargs["json"]
        assert "interaction_type" in post_data
        assert post_data["protocol_version"] == "2.0"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_generic_exception(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Non-A2AAgentError exception is wrapped."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        with pytest.raises(A2AAgentError, match="Failed to invoke"):
            await service.invoke_agent(mock_db, "ag", {})

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_metrics_error(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Metrics recording failure doesn't fail invocation."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_metrics_fn.side_effect = Exception("metrics down")

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        result = await service.invoke_agent(mock_db, "ag", {})
        assert result["ok"] is True

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_last_interaction_update_error(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Last interaction update failure doesn't fail invocation."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_metrics_fn.return_value = MagicMock()
        mock_fresh_db.return_value.__enter__.side_effect = Exception("db error")
        mock_fresh_db.return_value.__exit__.return_value = None

        result = await service.invoke_agent(mock_db, "ag", {})
        assert result["ok"] is True

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_last_interaction_skipped_when_disabled(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Disabled agents in the timestamp session skip last_interaction update."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        disabled_ts_agent = SimpleNamespace(enabled=False)

        def get_for_update(db, *_args, **_kwargs):
            return disabled_ts_agent if db is mock_ts_db else agent

        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", get_for_update)

        result = await service.invoke_agent(mock_db, "ag", {})
        assert result["ok"] is True
        mock_ts_db.commit.assert_not_called()

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_query_param_auth(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Query param auth decrypts and applies to URL."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/api",
            auth_type="query_param", auth_value=None,
            auth_query_params={"api_key": "encrypted_blob"},
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.decode_auth", lambda x: {"api_key": "secret123"})
        monkeypatch.setattr("mcpgateway.utils.url_auth.apply_query_param_auth", lambda url, params: url + "?api_key=secret123")
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        await service.invoke_agent(mock_db, "ag", {})
        # Verify the URL was modified with query params
        call_url = mock_client.post.call_args[0][0]
        assert "api_key=secret123" in call_url

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_query_param_auth_decrypt_error_is_skipped(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Query param decrypt failures are logged and skipped, without applying auth to URL."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/api",
            auth_type="query_param", auth_value=None,
            auth_query_params={"api_key": "bad", "empty": ""},
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.decode_auth", lambda _x: (_ for _ in ()).throw(ValueError("bad auth")))
        mock_apply = MagicMock()
        monkeypatch.setattr("mcpgateway.utils.url_auth.apply_query_param_auth", mock_apply)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.invoke_agent(mock_db, "ag", {})
        assert result["ok"] is True
        # No decrypted params => URL is unchanged and apply_query_param_auth not called
        call_url = mock_client.post.call_args[0][0]
        assert call_url == "https://x.com/api"
        mock_apply.assert_not_called()

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_auth_headers_from_dict(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """auth_value dict is used directly for supported auth types."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type="authheaders", auth_value={"X-API-Key": "secret"}, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.invoke_agent(mock_db, "ag", {})
        assert result["ok"] is True
        headers_used = mock_client.post.call_args.kwargs["headers"]
        assert headers_used.get("X-API-Key") == "secret"

    async def test_invoke_auth_value_decode_failure_raises(self, service, mock_db, monkeypatch):
        """decode_auth failures for auth_value raise A2AAgentError."""
        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type="basic", auth_value="bad", auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.decode_auth", lambda _x: (_ for _ in ()).throw(ValueError("bad")))

        with pytest.raises(A2AAgentError, match="Failed to decrypt authentication"):
            await service.invoke_agent(mock_db, "ag", {})

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_with_correlation_id(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Correlation ID is forwarded in outbound headers."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com/",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="generic", protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_correlation_id", lambda: "corr-123")
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        await service.invoke_agent(mock_db, "ag", {})
        headers_used = mock_client.post.call_args.kwargs["headers"]
        assert headers_used.get("X-Correlation-ID") == "corr-123"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_trailing_slash_does_not_switch_transport(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Trailing slash no longer switches transport; only agent_type controls it."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="custom",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        await service.invoke_agent(mock_db, "ag", {"test": "data"}, interaction_type="query")
        post_data = mock_client.post.call_args.kwargs["json"]
        assert "interaction_type" in post_data
        assert "jsonrpc" not in post_data

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_rest_mapping_includes_a2a_version_header(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """REST transport maps A2A methods to /v1 endpoints and includes A2A-Version header."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.request.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/base",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="a2a-rest",
            protocol_version="0.3",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.invoke_agent(
            mock_db,
            "ag",
            {
                "method": "message/send",
                "params": {"message": {"parts": [{"kind": "text", "text": "hi"}]}},
            },
        )
        assert result["ok"] is True

        call_args = mock_client.request.call_args
        assert call_args.args[0] == "POST"
        assert call_args.args[1].endswith("/base/v1/message:send")
        headers_used = call_args.kwargs["headers"]
        assert headers_used.get("A2A-Version") == "0.3"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_rest_passthrough_does_not_include_a2a_version_header(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """rest-passthrough sends raw JSON without A2A REST headers."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/passthrough",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="rest-passthrough",
            protocol_version="0.3",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.invoke_agent(mock_db, "ag", {"query": "hi"})
        assert result["ok"] is True
        headers_used = mock_client.post.call_args.kwargs["headers"]
        assert "A2A-Version" not in headers_used

    @patch("mcpgateway.services.oauth_manager.OAuthManager.get_access_token", new_callable=AsyncMock)
    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_oauth_sets_bearer_header(
        self, mock_get_client, mock_fresh_db, mock_metrics_fn, mock_get_access_token, service, mock_db, monkeypatch
    ):
        """OAuth auth_type uses OAuthManager to set Authorization header."""
        mock_get_access_token.return_value = "oauth-token"

        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com",
            auth_type="oauth",
            auth_value=None,
            auth_query_params=None,
            oauth_config={"grant_type": "client_credentials", "token_url": "https://oauth.example.com/token", "client_id": "id", "client_secret": "secret"},
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.invoke_agent(mock_db, "ag", {})
        assert result["ok"] is True
        headers_used = mock_client.post.call_args.kwargs["headers"]
        assert headers_used.get("Authorization") == "Bearer oauth-token"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_jsonrpc_alias_uses_uuid_and_normalizes_parts(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """generic/jsonrpc aliases route to JSON-RPC with UUID id and kind-based parts."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"result": {"ok": True}}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/custom-no-slash",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.invoke_agent(
            mock_db,
            "ag",
            {
                "method": "message/send",
                "params": {
                    "message": {
                        "parts": [{"type": "text", "text": "hi"}],
                    }
                },
            },
        )
        assert result == {"ok": True}

        request_data = mock_client.post.call_args.kwargs["json"]
        # Ensure string UUID id instead of static numeric id.
        assert isinstance(request_data["id"], str)
        uuid.UUID(request_data["id"])
        assert request_data["params"]["message"]["parts"][0]["kind"] == "text"
        assert "type" not in request_data["params"]["message"]["parts"][0]

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_jsonrpc_error_code_mapping(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """A2A JSON-RPC errors map canonical codes to descriptive failures."""
        mock_client = AsyncMock()
        mock_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"jsonrpc": "2.0", "id": "req-1", "error": {"code": -32001, "message": "task not found"}}),
        )
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="jsonrpc",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        with pytest.raises(A2AAgentError, match=r"TaskNotFoundError \(-32001\)"):
            await service.invoke_agent(mock_db, "ag", {"method": "tasks/get", "params": {"id": "missing"}})


class TestInvokeAgentGrpcTransport:
    """Cover gRPC transport path with mocked channel/stub (no real network)."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_agent_dispatches_to_grpc(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """invoke_agent routes a2a-grpc agent_type to _invoke_a2a_grpc and does not call HTTP."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.request = AsyncMock()
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="grpc://localhost:50051",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="grpc",
            protocol_version="0.3.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *_a, **_kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        service._invoke_a2a_grpc = AsyncMock(return_value={"ok": True})

        result = await service.invoke_agent(
            mock_db,
            "ag",
            {"method": "message/send", "params": {"message": {"messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}}},
        )

        assert result == {"ok": True}
        service._invoke_a2a_grpc.assert_awaited_once()
        mock_client.post.assert_not_called()
        mock_client.request.assert_not_called()

    async def test_invoke_a2a_grpc_send_message_over_insecure_channel(self, service):
        """_invoke_a2a_grpc SendMessage builds request and uses grpc.aio.insecure_channel for grpc:// endpoints."""
        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.SendMessage = AsyncMock(
            return_value=a2a_pb2.SendMessageResponse(
                msg=a2a_pb2.Message(message_id="resp-1", role=a2a_pb2.ROLE_AGENT),
            )
        )

        with (
            patch("grpc.aio.insecure_channel", return_value=channel) as mock_insecure,
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            result = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "message/send", "params": {"message": {"messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}}},
                interaction_type="message_send",
                auth_headers={"Authorization": "Bearer token"},
                correlation_id="corr-1",
            )

        assert result["message"]["messageId"] == "resp-1"
        mock_insecure.assert_called_once_with("localhost:50051")
        channel.close.assert_awaited_once()

        call_args = stub.SendMessage.call_args
        sent_request = call_args.args[0]
        sent_metadata = call_args.kwargs["metadata"]
        assert sent_request.request.message_id == "m1"
        assert sent_request.request.content[0].text == "hi"
        assert ("authorization", "Bearer token") in sent_metadata
        assert ("x-correlation-id", "corr-1") in sent_metadata

    async def test_invoke_a2a_grpc_send_streaming_message_collects_events(self, service):
        """_invoke_a2a_grpc SendStreamingMessage returns an events list."""
        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        async def stream():
            yield a2a_pb2.StreamResponse(msg=a2a_pb2.Message(message_id="m1"))
            yield a2a_pb2.StreamResponse(msg=a2a_pb2.Message(message_id="m2"))

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.SendStreamingMessage = MagicMock(return_value=stream())

        with (
            patch("grpc.aio.insecure_channel", return_value=channel),
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            result = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "message/stream", "params": {"message": {"messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}}},
                interaction_type="message_stream",
                auth_headers={},
                correlation_id=None,
            )

        assert [event["message"]["messageId"] for event in result["events"]] == ["m1", "m2"]

    async def test_invoke_a2a_grpc_task_subscription_collects_events(self, service):
        """_invoke_a2a_grpc TaskSubscription returns an events list."""
        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        async def stream():
            yield a2a_pb2.StreamResponse(task=a2a_pb2.Task(id="t1"))
            yield a2a_pb2.StreamResponse(task=a2a_pb2.Task(id="t1"))

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.TaskSubscription = MagicMock(return_value=stream())

        with (
            patch("grpc.aio.insecure_channel", return_value=channel),
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            result = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "tasks/subscribe", "params": {"id": "t1"}},
                interaction_type="task_subscription",
                auth_headers={},
                correlation_id=None,
            )

        assert result["events"][0]["task"]["id"] == "t1"

    async def test_invoke_a2a_grpc_get_and_cancel_task(self, service):
        """_invoke_a2a_grpc supports GetTask and CancelTask."""
        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.GetTask = AsyncMock(return_value=a2a_pb2.Task(id="t1"))
        stub.CancelTask = AsyncMock(return_value=a2a_pb2.Task(id="t1"))

        with (
            patch("grpc.aio.insecure_channel", return_value=channel),
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            result_get = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "tasks/get", "params": {"id": "t1", "history_length": 2}},
                interaction_type="get_task",
                auth_headers={},
                correlation_id=None,
            )
            result_cancel = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "tasks/cancel", "params": {"id": "t1"}},
                interaction_type="cancel_task",
                auth_headers={},
                correlation_id=None,
            )

        assert result_get["id"] == "t1"
        assert result_cancel["id"] == "t1"

        sent_get_request = stub.GetTask.call_args.args[0]
        assert sent_get_request.name == "tasks/t1"
        assert sent_get_request.history_length == 2

        sent_cancel_request = stub.CancelTask.call_args.args[0]
        assert sent_cancel_request.name == "tasks/t1"

    async def test_invoke_a2a_grpc_get_agent_card(self, service):
        """_invoke_a2a_grpc supports GetAgentCard."""
        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.GetAgentCard = AsyncMock(return_value=a2a_pb2.AgentCard(name="demo-agent", url="https://agent.example.com", protocol_version="0.3"))

        with (
            patch("grpc.aio.insecure_channel", return_value=channel),
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            result = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "agent/getCard", "params": {}},
                interaction_type="agent_card",
                auth_headers={},
                correlation_id=None,
            )

        assert result["name"] == "demo-agent"
        stub.GetAgentCard.assert_awaited_once()

    async def test_invoke_a2a_grpc_create_task_push_notification_config(self, service):
        """_invoke_a2a_grpc supports CreateTaskPushNotificationConfig."""
        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.CreateTaskPushNotificationConfig = AsyncMock(
            return_value=a2a_pb2.TaskPushNotificationConfig(
                name="tasks/t1/pushNotificationConfigs/cfg-1",
                push_notification_config=a2a_pb2.PushNotificationConfig(id="cfg-1", url="https://webhook.example.com"),
            )
        )

        with (
            patch("grpc.aio.insecure_channel", return_value=channel),
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            result = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={
                    "method": "tasks/pushNotificationConfig/set",
                    "params": {
                        "id": "t1",
                        "configId": "cfg-1",
                        "config": {
                            "pushNotificationConfig": {
                                "id": "cfg-1",
                                "url": "https://webhook.example.com",
                            }
                        },
                    },
                },
                interaction_type="tasks_push_notification_set",
                auth_headers={},
                correlation_id=None,
            )

        assert result["name"] == "tasks/t1/pushNotificationConfigs/cfg-1"
        sent_request = stub.CreateTaskPushNotificationConfig.call_args.args[0]
        assert sent_request.parent == "tasks/t1"
        assert sent_request.config_id == "cfg-1"

    async def test_invoke_a2a_grpc_get_list_delete_task_push_notification_config(self, service):
        """_invoke_a2a_grpc supports Get/List/Delete task push-notification config operations."""
        # Third-Party
        from google.protobuf import empty_pb2

        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.GetTaskPushNotificationConfig = AsyncMock(
            return_value=a2a_pb2.TaskPushNotificationConfig(name="tasks/t1/pushNotificationConfigs/cfg-1")
        )
        stub.ListTaskPushNotificationConfig = AsyncMock(
            return_value=a2a_pb2.ListTaskPushNotificationConfigResponse(
                configs=[a2a_pb2.TaskPushNotificationConfig(name="tasks/t1/pushNotificationConfigs/cfg-1")],
                next_page_token="next-token",
            )
        )
        stub.DeleteTaskPushNotificationConfig = AsyncMock(return_value=empty_pb2.Empty())

        with (
            patch("grpc.aio.insecure_channel", return_value=channel),
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            got = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "tasks/pushNotificationConfig/get", "params": {"id": "t1", "configId": "cfg-1"}},
                interaction_type="tasks_push_notification_get",
                auth_headers={},
                correlation_id=None,
            )
            listed = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "tasks/pushNotificationConfig/list", "params": {"id": "t1", "page_size": 10, "page_token": "start"}},
                interaction_type="tasks_push_notification_list",
                auth_headers={},
                correlation_id=None,
            )
            deleted = await service._invoke_a2a_grpc(
                endpoint_url="grpc://localhost:50051",
                parameters={"method": "tasks/pushNotificationConfig/delete", "params": {"id": "t1", "configId": "cfg-1"}},
                interaction_type="tasks_push_notification_delete",
                auth_headers={},
                correlation_id=None,
            )

        assert got["name"] == "tasks/t1/pushNotificationConfigs/cfg-1"
        assert listed["configs"][0]["name"] == "tasks/t1/pushNotificationConfigs/cfg-1"
        assert listed["nextPageToken"] == "next-token"
        assert deleted == {}

        sent_list_request = stub.ListTaskPushNotificationConfig.call_args.args[0]
        assert sent_list_request.parent == "tasks/t1"
        assert sent_list_request.page_size == 10
        assert sent_list_request.page_token == "start"

    async def test_invoke_a2a_grpc_uses_secure_channel_for_grpcs(self, service):
        """grpcs:// endpoints use grpc.aio.secure_channel."""
        # First-Party
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2

        channel = MagicMock()
        channel.close = AsyncMock()

        stub = MagicMock()
        stub.SendMessage = AsyncMock(return_value=a2a_pb2.SendMessageResponse(msg=a2a_pb2.Message(message_id="m1")))

        with (
            patch("grpc.ssl_channel_credentials", return_value=MagicMock()) as mock_creds,
            patch("grpc.aio.secure_channel", return_value=channel) as mock_secure,
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            result = await service._invoke_a2a_grpc(
                endpoint_url="grpcs://example.com:443",
                parameters={"method": "message/send", "params": {"message": {"messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}}},
                interaction_type="message_send",
                auth_headers={},
                correlation_id=None,
            )

        assert result["message"]["messageId"] == "m1"
        mock_creds.assert_called_once()
        mock_secure.assert_called_once()
        assert mock_secure.call_args.args[0] == "example.com:443"

    async def test_invoke_a2a_grpc_maps_rpc_errors(self, service):
        """gRPC failures are mapped to A2AAgentError with status+details."""
        # Third-Party
        import grpc

        channel = MagicMock()
        channel.close = AsyncMock()

        class FakeRpcError(grpc.RpcError):
            def code(self):  # noqa: D401
                return grpc.StatusCode.UNAVAILABLE

            def details(self):  # noqa: D401
                return "connection refused"

        stub = MagicMock()
        stub.SendMessage = AsyncMock(side_effect=FakeRpcError())

        with (
            patch("grpc.aio.insecure_channel", return_value=channel),
            patch("mcpgateway.plugins.framework.external.grpc.proto.a2a_pb2_grpc.A2AServiceStub", return_value=stub),
        ):
            with pytest.raises(A2AAgentError, match=r"A2A gRPC SendMessage failed \(UNAVAILABLE\): connection refused"):
                await service._invoke_a2a_grpc(
                    endpoint_url="grpc://localhost:50051",
                    parameters={"method": "message/send", "params": {"message": {"messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}}},
                    interaction_type="message_send",
                    auth_headers={},
                    correlation_id=None,
                )

        channel.close.assert_awaited_once()


class TestA2AServiceWrapperMethods:
    """Cover the v0.3 wrapper methods that delegate to invoke_agent/_build_sse_stream."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_send_message_delegates_to_invoke_agent(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, monkeypatch):
        """send_message wraps invoke_agent with method='message/send'."""
        mock_db = MagicMock(spec=Session)
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"result": {"id": "t1"}}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="a2a-jsonrpc", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.send_message(db=mock_db, agent_name="ag", message_params={"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}})
        assert result == {"id": "t1"}
        post_data = mock_client.post.call_args.kwargs["json"]
        assert post_data["method"] == "message/send"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_get_task_delegates_to_invoke_agent(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, monkeypatch):
        """get_task wraps invoke_agent with method='tasks/get' and params.id=task_id."""
        mock_db = MagicMock(spec=Session)
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"result": {"id": "t1", "status": {"state": "completed"}}}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="a2a-jsonrpc", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.get_task(db=mock_db, agent_name="ag", task_id="t1")
        assert result["id"] == "t1"
        post_data = mock_client.post.call_args.kwargs["json"]
        assert post_data["method"] == "tasks/get"
        assert post_data["params"]["id"] == "t1"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_list_tasks_delegates_to_invoke_agent(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, monkeypatch):
        """list_tasks wraps invoke_agent with method='tasks/list'."""
        mock_db = MagicMock(spec=Session)
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"result": {"tasks": []}}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="a2a-jsonrpc", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.list_tasks(db=mock_db, agent_name="ag", params={"state": "completed"})
        post_data = mock_client.post.call_args.kwargs["json"]
        assert post_data["method"] == "tasks/list"
        assert post_data["params"]["state"] == "completed"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_cancel_task_delegates_to_invoke_agent(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, monkeypatch):
        """cancel_task wraps invoke_agent with method='tasks/cancel' and params.id=task_id."""
        mock_db = MagicMock(spec=Session)
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"result": {"id": "t1", "status": {"state": "canceled"}}}))
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="a2a-jsonrpc", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.cancel_task(db=mock_db, agent_name="ag", task_id="t1")
        post_data = mock_client.post.call_args.kwargs["json"]
        assert post_data["method"] == "tasks/cancel"
        assert post_data["params"]["id"] == "t1"

    async def test_stream_message_calls_build_sse_stream(self, service, monkeypatch):
        """stream_message delegates to _build_sse_stream with correct method."""

        async def _fake_gen():
            yield b"data: {}\n\n"

        async def _fake_build(*args, **kwargs):
            assert kwargs["rpc_method"] == "message/stream"
            assert kwargs["interaction_type"] == "message_stream"
            return _fake_gen()

        monkeypatch.setattr(service, "_build_sse_stream", _fake_build)
        result = await service.stream_message(db=MagicMock(), agent_name="ag", message_params={"message": {"parts": []}})
        chunks = [chunk async for chunk in result]
        assert len(chunks) == 1

    async def test_subscribe_task_calls_build_sse_stream(self, service, monkeypatch):
        """subscribe_task delegates to _build_sse_stream with tasks/subscribe method."""

        async def _fake_gen():
            yield b"event: status\n"

        async def _fake_build(*args, **kwargs):
            assert kwargs["rpc_method"] == "tasks/subscribe"
            assert kwargs["interaction_type"] == "tasks_subscribe"
            assert kwargs["rpc_params"]["id"] == "t1"
            return _fake_gen()

        monkeypatch.setattr(service, "_build_sse_stream", _fake_build)
        result = await service.subscribe_task(db=MagicMock(), agent_name="ag", task_id="t1")
        chunks = [chunk async for chunk in result]
        assert len(chunks) == 1

    async def test_get_agent_card_delegates_to_invoke_agent(self, service, monkeypatch):
        """get_agent_card wraps invoke_agent with method='agent/getCard'."""
        captured = {}

        async def _fake_invoke(db, agent_name, parameters, interaction_type, **kw):
            captured["method"] = parameters.get("method")
            captured["interaction_type"] = interaction_type
            return {"name": "test-agent", "url": "https://example.com"}

        monkeypatch.setattr(service, "invoke_agent", _fake_invoke)
        result = await service.get_agent_card(db=MagicMock(), agent_name="ag")
        assert result["name"] == "test-agent"
        assert captured["method"] == "agent/getCard"
        assert captured["interaction_type"] == "agent_card"


class TestBuildSseStream:
    """Cover _build_sse_stream for HTTP and error paths."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    async def test_build_sse_stream_agent_not_found(self, service, monkeypatch):
        """_build_sse_stream raises A2AAgentNotFoundError for missing agent."""
        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(A2AAgentNotFoundError):
            await service._build_sse_stream(db=mock_db, agent_name="missing", rpc_method="message/stream", rpc_params={}, interaction_type="stream")

    async def test_build_sse_stream_agent_disabled(self, service, monkeypatch):
        """_build_sse_stream raises A2AAgentError for disabled agent."""
        mock_db = MagicMock(spec=Session)
        agent = SimpleNamespace(
            id="a1", name="ag", enabled=False, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="a2a-jsonrpc", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)

        with pytest.raises(A2AAgentError, match="disabled"):
            await service._build_sse_stream(db=mock_db, agent_name="ag", rpc_method="message/stream", rpc_params={}, interaction_type="stream")

    async def test_build_sse_stream_access_denied(self, service, monkeypatch):
        """_build_sse_stream raises A2AAgentNotFoundError for denied access."""
        mock_db = MagicMock(spec=Session)
        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="private", team_id=None, owner_email="other@example.com",
            agent_type="a2a-jsonrpc", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)

        with pytest.raises(A2AAgentNotFoundError):
            await service._build_sse_stream(
                db=mock_db, agent_name="ag",
                rpc_method="message/stream", rpc_params={},
                interaction_type="stream",
                user_email="someone@test.com", token_teams=[],
            )

    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_build_sse_stream_jsonrpc_transport(self, mock_get_client, service, monkeypatch):
        """_build_sse_stream returns HTTP stream for a2a-jsonrpc transport."""
        mock_db = MagicMock(spec=Session)
        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="a2a-jsonrpc", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        # The generator is returned immediately; we just verify it's an async generator.
        result = await service._build_sse_stream(
            db=mock_db, agent_name="ag",
            rpc_method="message/stream", rpc_params={"message": {"parts": []}},
            interaction_type="message_stream",
        )
        # Result should be an async generator (not None)
        assert hasattr(result, "__aiter__")

    async def test_build_sse_stream_unsupported_transport_raises(self, service, monkeypatch):
        """_build_sse_stream raises for unsupported transport types."""
        mock_db = MagicMock(spec=Session)
        agent = SimpleNamespace(
            id="a1", name="ag", enabled=True, endpoint_url="https://x.com",
            auth_type=None, auth_value=None, auth_query_params=None,
            visibility="public", team_id=None, owner_email=None,
            agent_type="custom", protocol_version="0.3", oauth_config=None,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        with pytest.raises(A2AAgentError, match="not supported"):
            await service._build_sse_stream(
                db=mock_db, agent_name="ag",
                rpc_method="message/stream", rpc_params={},
                interaction_type="stream",
            )


class TestExtractAndUpsertTasks:
    """Cover _extract_task_payloads and _upsert_a2a_task."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    def test_extract_task_payloads_from_result(self, service):
        """Extract tasks from a JSON-RPC result envelope."""
        payload = {
            "result": {
                "id": "t1",
                "status": {"state": "completed"},
            }
        }
        tasks = service._extract_task_payloads(payload)
        assert len(tasks) == 1
        assert tasks[0]["id"] == "t1"

    def test_extract_task_payloads_from_list(self, service):
        """Extract multiple tasks from a list response."""
        payload = {
            "tasks": [
                {"id": "t1", "status": {"state": "completed"}},
                {"id": "t2", "status": {"state": "working"}},
            ]
        }
        tasks = service._extract_task_payloads(payload)
        assert len(tasks) == 2
        task_ids = {t["id"] for t in tasks}
        assert task_ids == {"t1", "t2"}

    def test_extract_task_payloads_deduplicates(self, service):
        """Same task_id appearing multiple times is deduplicated."""
        payload = {
            "result": {"id": "t1", "status": {"state": "completed"}},
            "task": {"id": "t1", "status": {"state": "working"}},
        }
        tasks = service._extract_task_payloads(payload)
        assert len(tasks) == 1

    def test_extract_task_payloads_ignores_non_tasks(self, service):
        """Payloads without id+status dict are not extracted."""
        payload = {"result": {"message": "hello"}}
        tasks = service._extract_task_payloads(payload)
        assert len(tasks) == 0

    def test_upsert_a2a_task_creates_new(self, service):
        """_upsert_a2a_task inserts a new task row."""
        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        now = datetime.now(timezone.utc)
        result = service._upsert_a2a_task(mock_db, "agent-1", {"id": "t1", "status": {"state": "working"}}, now)
        assert result is True
        mock_db.add.assert_called_once()

    def test_upsert_a2a_task_updates_existing(self, service):
        """_upsert_a2a_task updates an existing task row."""
        mock_db = MagicMock(spec=Session)
        existing = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = existing

        now = datetime.now(timezone.utc)
        result = service._upsert_a2a_task(mock_db, "agent-1", {"id": "t1", "status": {"state": "completed"}}, now)
        assert result is True
        assert existing.state == "completed"
        assert existing.completed_at == now

    def test_upsert_a2a_task_rejects_missing_id(self, service):
        """_upsert_a2a_task returns False for payloads without task id."""
        mock_db = MagicMock(spec=Session)
        now = datetime.now(timezone.utc)
        result = service._upsert_a2a_task(mock_db, "agent-1", {"status": {"state": "completed"}}, now)
        assert result is False


class TestConvertAgentToRead:
    """Cover convert_agent_to_read branches: not found, team lookup, metrics."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    def test_not_found_raises(self, service):
        with pytest.raises(A2AAgentNotFoundError, match="not found"):
            service.convert_agent_to_read(None)

    def test_team_from_team_map(self, service):
        """Team name is resolved from team_map when provided."""
        agent = MagicMock()
        agent.team = None  # not pre-populated
        agent.team_id = "t1"
        agent.auth_value = None
        agent.auth_query_params = None

        mock_validated = MagicMock()
        mock_validated.masked.return_value = mock_validated
        with patch.object(A2AAgentRead, "model_validate", return_value=mock_validated):
            result = service.convert_agent_to_read(agent, team_map={"t1": "Alpha"})
        assert result is mock_validated

    def test_team_from_db(self, service):
        """Team name is resolved from DB when team_map not provided."""
        agent = MagicMock()
        agent.team = None
        agent.team_id = "t1"
        agent.auth_value = None
        agent.auth_query_params = None

        mock_db = MagicMock()
        service._get_team_name = MagicMock(return_value="Beta")

        mock_validated = MagicMock()
        mock_validated.masked.return_value = mock_validated
        with patch.object(A2AAgentRead, "model_validate", return_value=mock_validated):
            service.convert_agent_to_read(agent, db=mock_db)
        service._get_team_name.assert_called_once()

    def test_with_metrics(self, service):
        """Metrics are computed when include_metrics=True."""
        m1 = SimpleNamespace(is_success=True, response_time=1.0, timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc))
        m2 = SimpleNamespace(is_success=False, response_time=3.0, timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc))
        agent = MagicMock()
        agent.team = "Team"
        agent.team_id = None
        agent.auth_value = None
        agent.auth_query_params = None
        agent.metrics = [m1, m2]

        mock_validated = MagicMock()
        mock_validated.masked.return_value = mock_validated
        with patch.object(A2AAgentRead, "model_validate", return_value=mock_validated) as mock_mv:
            service.convert_agent_to_read(agent, include_metrics=True)

            # Verify model_validate was called with metrics included
            call_data = mock_mv.call_args[0][0]
            assert call_data["metrics"] is not None
            assert call_data["metrics"].total_executions == 2
            assert call_data["metrics"].successful_executions == 1

    def test_with_metrics_empty_list(self, service):
        """include_metrics=True with no metrics avoids response-time calculations."""
        agent = MagicMock()
        agent.team = "Team"
        agent.team_id = None
        agent.auth_value = None
        agent.auth_query_params = None
        agent.metrics = []

        mock_validated = MagicMock()
        mock_validated.masked.return_value = mock_validated
        with patch.object(A2AAgentRead, "model_validate", return_value=mock_validated) as mock_mv:
            service.convert_agent_to_read(agent, include_metrics=True)
            call_data = mock_mv.call_args[0][0]
            assert call_data["metrics"] is not None
            assert call_data["metrics"].total_executions == 0

    def test_with_metrics_response_times_missing(self, service):
        """Metrics branch handles metrics without response_time values."""
        m1 = SimpleNamespace(is_success=True, response_time=None, timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc))
        agent = MagicMock()
        agent.team = "Team"
        agent.team_id = None
        agent.auth_value = None
        agent.auth_query_params = None
        agent.metrics = [m1]

        mock_validated = MagicMock()
        mock_validated.masked.return_value = mock_validated
        with patch.object(A2AAgentRead, "model_validate", return_value=mock_validated) as mock_mv:
            service.convert_agent_to_read(agent, include_metrics=True)
            call_data = mock_mv.call_args[0][0]
            assert call_data["metrics"].min_response_time is None

    def test_no_team_no_db(self, service):
        """No team_map, no db → team_name stays None."""
        agent = MagicMock()
        agent.team = None
        agent.team_id = "t1"
        agent.auth_value = None
        agent.auth_query_params = None

        mock_validated = MagicMock()
        mock_validated.masked.return_value = mock_validated
        with patch.object(A2AAgentRead, "model_validate", return_value=mock_validated):
            service.convert_agent_to_read(agent)
        # team was set to None since no db or team_map
        assert agent.team is None


class TestAggregateMetricsEdgeCases:
    """Cover aggregate_metrics cache hit and cache write branches."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_cache_hit(self, service, mock_db, monkeypatch):
        """Cached metrics are returned without DB query."""
        cached_metrics = {"total_agents": 5, "active_agents": 3, "total_interactions": 100}

        monkeypatch.setattr("mcpgateway.cache.metrics_cache.is_cache_enabled", lambda: True)
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", SimpleNamespace(
            get=MagicMock(return_value=cached_metrics),
        ))

        result = await service.aggregate_metrics(mock_db)
        assert result == cached_metrics

    async def test_cache_write(self, service, mock_db, monkeypatch):
        """Computed metrics are written to cache."""
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        mock_metrics = AggregatedMetrics(
            total_executions=10, successful_executions=8, failed_executions=2,
            failure_rate=0.2, min_response_time=0.1, max_response_time=2.0,
            avg_response_time=1.0, last_execution_time=None, raw_count=10, rollup_count=0,
        )

        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # cache miss
        mock_cache.set = MagicMock()

        monkeypatch.setattr("mcpgateway.cache.metrics_cache.is_cache_enabled", lambda: True)
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", mock_cache)
        monkeypatch.setattr("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", lambda db, t: mock_metrics)

        # Mock agent counts
        mock_counts_result = MagicMock()
        mock_counts_result.total = 3
        mock_counts_result.active = 2
        mock_db.execute.return_value.one.return_value = mock_counts_result

        result = await service.aggregate_metrics(mock_db)
        assert result["total_agents"] == 3
        mock_cache.set.assert_called_once()
