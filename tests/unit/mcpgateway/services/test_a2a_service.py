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
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.schemas import A2AAgentCreate, A2AAgentRead, A2AAgentUpdate
from mcpgateway.services.rust_a2a_runtime import RustA2ARuntimeError
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNameConflictError, A2AAgentNotFoundError, A2AAgentService
from mcpgateway.services.encryption_service import get_encryption_service
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
        # First-Party
        import mcpgateway.schemas

        if hasattr(mcpgateway.schemas.ToolRead, "model_validate"):
            # Standard
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

    async def test_register_agent_encrypts_oauth_sensitive_values(self, service, mock_db):
        """register_agent encrypts oauth_config secret values before persistence."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        captured_agent = None

        def _capture_add(obj):
            nonlocal captured_agent
            if isinstance(obj, DbA2AAgent):
                captured_agent = obj

        mock_db.add = MagicMock(side_effect=_capture_add)
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        agent_data = A2AAgentCreate(
            name="oauth-agent",
            description="oauth",
            endpoint_url="https://api.example.com/agent",
            agent_type="custom",
            protocol_version="1.0",
            capabilities={},
            config={},
            auth_type="oauth",
            oauth_config={
                "grant_type": "password",
                "client_id": "cid",
                "client_secret": "super-secret",
                "password": "pw",
                "token_url": "https://auth.example.com/token",
                "username": "svc-user",
            },
            tags=[],
        )

        with patch("mcpgateway.schemas.ToolRead.model_validate", return_value=MagicMock()):
            await service.register_agent(mock_db, agent_data)

        assert captured_agent is not None
        encryption = get_encryption_service(settings.auth_encryption_secret)
        assert encryption.is_encrypted(captured_agent.oauth_config["client_secret"])
        assert encryption.is_encrypted(captured_agent.oauth_config["password"])
        assert captured_agent.oauth_config["grant_type"] == "password"

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

    async def test_update_agent_team_id_rejects_nonexistent_team(self, service, mock_db, sample_db_agent):
        """Reassigning an agent to a non-existent team must raise A2AAgentError."""
        sample_db_agent.version = 1
        sample_db_agent.team_id = "00000000-0000-0000-0000-000000000001"

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = None  # team not found
            mock_db.query.return_value = mock_query

            update_data = A2AAgentUpdate(team_id="00000000-0000-0000-0000-000000000099")

            with pytest.raises(A2AAgentError, match="not found"):
                await service.update_agent(mock_db, sample_db_agent.id, update_data)

    async def test_update_agent_visibility_team_without_team_id_rejects(self, service, mock_db, sample_db_agent):
        """Setting visibility to 'team' without any team_id must raise A2AAgentError."""
        sample_db_agent.version = 1
        sample_db_agent.team_id = None

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = None
            mock_db.query.return_value = mock_query

            update_data = A2AAgentUpdate(visibility="team")

            with pytest.raises(A2AAgentError, match="without a team_id"):
                await service.update_agent(mock_db, sample_db_agent.id, update_data)

    async def test_update_agent_team_id_rejects_non_owner(self, service, mock_db, sample_db_agent):
        """Reassigning an agent to a team where user is not owner must raise."""
        # First-Party
        from mcpgateway.services.a2a_service import _validate_a2a_team_assignment

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        # Team exists but membership check returns None
        mock_query.first.side_effect = [MagicMock(), None]

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query

        with pytest.raises(ValueError, match="membership"):
            _validate_a2a_team_assignment(mock_session, "user@example.com", "00000000-0000-0000-0000-000000000099")

    async def test_update_agent_team_id_skips_ownership_without_user_email(self, service, mock_db, sample_db_agent):
        """System updates without user_email skip ownership checks and persist team_id."""
        sample_db_agent.version = 1
        sample_db_agent.team_id = "00000000-0000-0000-0000-000000000001"

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = MagicMock()  # Team exists
            mock_db.query.return_value = mock_query

            with patch.object(service, "convert_agent_to_read", return_value=MagicMock()):
                update_data = A2AAgentUpdate(team_id="00000000-0000-0000-0000-000000000099")
                await service.update_agent(mock_db, sample_db_agent.id, update_data, user_email=None)

        # UUID is normalized by schema
        assert sample_db_agent.team_id == "00000000000000000000000000000099"

    async def test_update_agent_encrypts_oauth_sensitive_values(self, service, mock_db, sample_db_agent):
        """update_agent encrypts oauth_config secrets before saving."""
        sample_db_agent.version = 1
        sample_db_agent.oauth_config = None

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            with patch.object(service, "convert_agent_to_read", return_value=MagicMock()):
                update_data = A2AAgentUpdate(
                    oauth_config={
                        "grant_type": "password",
                        "client_id": "cid",
                        "client_secret": "new-secret",
                        "password": "new-pw",
                        "token_url": "https://auth.example.com/token",
                    }
                )
                await service.update_agent(mock_db, sample_db_agent.id, update_data)

        encryption = get_encryption_service(settings.auth_encryption_secret)
        assert encryption.is_encrypted(sample_db_agent.oauth_config["client_secret"])
        assert encryption.is_encrypted(sample_db_agent.oauth_config["password"])
        assert sample_db_agent.oauth_config["grant_type"] == "password"

    async def test_update_agent_oauth_masked_placeholder_preserves_existing_secret(self, service, mock_db, sample_db_agent):
        """Masked oauth secret placeholders preserve existing encrypted values."""
        sample_db_agent.version = 1
        encryption = get_encryption_service(settings.auth_encryption_secret)
        existing_secret = await encryption.encrypt_secret_async("existing-secret")
        sample_db_agent.oauth_config = {"grant_type": "client_credentials", "client_secret": existing_secret}

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            with patch.object(service, "convert_agent_to_read", return_value=MagicMock()):
                update_data = A2AAgentUpdate(
                    oauth_config={
                        "grant_type": "client_credentials",
                        "client_secret": settings.masked_auth_value,
                    }
                )
                await service.update_agent(mock_db, sample_db_agent.id, update_data)

        assert sample_db_agent.oauth_config["client_secret"] == existing_secret

    async def test_update_agent_masked_auth_headers_preserves_existing_values(self, service, mock_db, sample_db_agent):
        """Masked auth_headers placeholders preserve existing encrypted header values (issue #3637)."""
        sample_db_agent.version = 1
        sample_db_agent.auth_type = "authheaders"
        sample_db_agent.auth_value = encode_auth({"X-API-Key": "real-secret-123", "X-Client-ID": "real-client-456"})

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            with patch.object(service, "convert_agent_to_read", return_value=MagicMock()):
                # Simulate what the UI sends: masked values for unchanged headers
                update_data = A2AAgentUpdate(
                    auth_type="authheaders",
                    auth_headers=[
                        {"key": "X-API-Key", "value": settings.masked_auth_value},
                        {"key": "X-Client-ID", "value": settings.masked_auth_value},
                    ],
                )
                await service.update_agent(mock_db, sample_db_agent.id, update_data)

        # First-Party
        from mcpgateway.utils.services_auth import decode_auth

        persisted = decode_auth(sample_db_agent.auth_value)
        assert persisted["X-API-Key"] == "real-secret-123", "Masked placeholder must not overwrite real credential"
        assert persisted["X-Client-ID"] == "real-client-456", "Masked placeholder must not overwrite real credential"

    async def test_update_agent_mixed_masked_and_new_auth_headers(self, service, mock_db, sample_db_agent):
        """When some headers are masked and one is changed, only the changed header is updated."""
        sample_db_agent.version = 1
        sample_db_agent.auth_type = "authheaders"
        sample_db_agent.auth_value = encode_auth({"X-API-Key": "original-secret", "X-Client-ID": "original-client"})

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            with patch.object(service, "convert_agent_to_read", return_value=MagicMock()):
                update_data = A2AAgentUpdate(
                    auth_type="authheaders",
                    auth_headers=[
                        {"key": "X-API-Key", "value": settings.masked_auth_value},  # unchanged
                        {"key": "X-Client-ID", "value": "new-client-value"},  # user changed this
                    ],
                )
                await service.update_agent(mock_db, sample_db_agent.id, update_data)

        # First-Party
        from mcpgateway.utils.services_auth import decode_auth

        persisted = decode_auth(sample_db_agent.auth_value)
        assert persisted["X-API-Key"] == "original-secret", "Unchanged masked header must be preserved"
        assert persisted["X-Client-ID"] == "new-client-value", "Changed header must be updated"

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
            with patch("mcpgateway.services.a2a_protocol.decode_auth", return_value=basic_auth_headers):
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
            with patch("mcpgateway.services.a2a_protocol.decode_auth", return_value=bearer_auth_headers):
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
            with patch("mcpgateway.services.a2a_protocol.decode_auth", return_value=custom_auth_headers):
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
        # First-Party
        from mcpgateway.schemas import A2AAgentAggregateMetrics
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

        # Mock agent counts via a2a_stats_cache (avoids singleton cache interference)
        with (
            patch("mcpgateway.cache.a2a_stats_cache.a2a_stats_cache.get_counts", return_value={"total": 5, "active": 3}),
            patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_metrics),
        ):
            result = await service.aggregate_metrics(mock_db)

        # Verify result is an A2AAgentAggregateMetrics instance
        assert isinstance(result, A2AAgentAggregateMetrics)
        assert result.total_agents == 5
        assert result.active_agents == 3
        assert result.total_interactions == 100
        assert result.successful_interactions == 90
        assert result.failed_interactions == 10
        assert result.success_rate == 90.0
        assert result.avg_response_time == 1.5
        assert result.min_response_time == 0.5
        assert result.max_response_time == 3.0

        # Verify camelCase serialization
        result_dict = result.model_dump(by_alias=True)
        assert "totalAgents" in result_dict
        assert "activeAgents" in result_dict
        assert "totalInteractions" in result_dict
        assert "successfulInteractions" in result_dict
        assert "failedInteractions" in result_dict
        assert "successRate" in result_dict
        assert "avgResponseTime" in result_dict
        assert "minResponseTime" in result_dict
        assert "maxResponseTime" in result_dict

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
        # Full admin bypass (both None) grants access to team agents
        assert service._check_agent_access(agent, user_email=None, token_teams=None) is True
        # No user context (user_email=None) denies access to non-public agents
        assert service._check_agent_access(agent, user_email=None, token_teams=["team-1"]) is False
        # Admin bypass: token_teams=None grants access regardless of user_email
        assert service._check_agent_access(agent, user_email="admin@example.com", token_teams=None) is True
        # With user context, team membership grants access
        assert service._check_agent_access(agent, user_email="someone@example.com", token_teams=["team-1"]) is True
        assert service._check_agent_access(agent, user_email="someone@example.com", token_teams=["other"]) is False

        agent.visibility = "private"
        # Public-only tokens (token_teams=[]) cannot access private agents even as owner
        assert service._check_agent_access(agent, user_email="owner@example.com", token_teams=[]) is False
        # Team-scoped tokens: owner can access their own private agents
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

        # First-Party
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
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, owner_email="owner@x.com", tool_id=None)
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
        agent = SimpleNamespace(id="a1", enabled=False, name="ag", reachable=False, tool_id=None)
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
            name="test-agent",
            endpoint_url="https://api.example.com/agent",
            agent_type="custom",
            protocol_version="1.0",
            capabilities={},
            config={},
        )

    async def test_register_integrity_error(self, service, mock_db, agent_data, monkeypatch):
        """IntegrityError from DB is re-raised."""
        # Third-Party
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

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = False
            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent",
                slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom",
                protocol_version="1.0",
                capabilities={},
                config={},
                tags=[],
                auth_type="query_param",
                auth_query_param_key="key",
                auth_query_param_value="val",
            )
            with pytest.raises(ValueError, match="disabled"):
                await service.register_agent(mock_db, agent_data)

    async def test_register_query_param_host_not_allowed(self, service, mock_db, monkeypatch):
        """Query param auth host not in allowlist raises ValueError."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: None)

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = ["safe.host.com"]
            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent",
                slug="qp-agent",
                endpoint_url="https://bad.host.com/agent",
                agent_type="custom",
                protocol_version="1.0",
                capabilities={},
                config={},
                tags=[],
                auth_type="query_param",
                auth_query_param_key="key",
                auth_query_param_value="val",
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

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = []

            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent",
                slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom",
                protocol_version="1.0",
                capabilities={},
                config={},
                tags=[],
                auth_type="query_param",
                auth_query_param_key="api_key",
                auth_query_param_value=secret_val,
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

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = []

            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent",
                slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom",
                protocol_version="1.0",
                capabilities={},
                config={},
                tags=[],
                auth_type="query_param",
                auth_query_param_key="api_key",
                auth_query_param_value=123,
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

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
            mock_settings.insecure_allow_queryparam_auth = True
            mock_settings.insecure_queryparam_auth_allowed_hosts = []

            agent_data = A2AAgentCreate.model_construct(
                name="qp-agent",
                slug="qp-agent",
                endpoint_url="https://api.example.com/agent",
                agent_type="custom",
                protocol_version="1.0",
                capabilities={},
                config={},
                tags=[],
                auth_type="query_param",
                auth_query_param_key=None,
                auth_query_param_value=None,
            )
            with patch("mcpgateway.services.tool_service.tool_service") as ts:
                ts.create_tool_from_a2a_agent = AsyncMock(return_value=None)
                service.convert_agent_to_read = MagicMock(return_value=MagicMock())
                await service.register_agent(mock_db, agent_data)

        added_agent = mock_db.add.call_args[0][0]
        assert added_agent.auth_query_params is None


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

        with patch("mcpgateway.services.base_service.TeamManagementService") as tm_cls:
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
        monkeypatch.setattr(
            "mcpgateway.services.a2a_service.unified_paginate",
            AsyncMock(
                return_value={
                    "data": [agent],
                    "pagination": {"page": 1, "total": 1},
                    "links": {},
                }
            ),
        )
        mock_db.execute.return_value.all.return_value = []
        mock_db.commit = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        result = await service.list_agents(mock_db, page=1, per_page=10)
        assert isinstance(result, dict)
        assert "data" in result
        assert "pagination" in result

    async def test_list_validation_error_skips_agent(self, service, mock_db, monkeypatch):
        """ValidationError during conversion skips agent instead of failing."""
        # Third-Party
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

    async def test_list_cache_read_reconstructs_and_masks(self, service, mock_db, monkeypatch):
        """Cached A2A entries are reconstructed and re-masked before returning."""
        cache = SimpleNamespace(
            hash_filters=MagicMock(return_value="h"),
            get=AsyncMock(return_value={"agents": [{"id": "a1"}], "next_cursor": "cursor-1"}),
            set=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        class CachedAgentRead:
            def __init__(self):
                self.masked_called = False

            def masked(self):
                self.masked_called = True
                return self

        cached_agent_read = CachedAgentRead()
        with patch("mcpgateway.services.a2a_service.A2AAgentRead.model_validate", return_value=cached_agent_read):
            result, cursor = await service.list_agents(mock_db)

        assert result == [cached_agent_read]
        assert result[0].masked_called is True
        assert cursor == "cursor-1"


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
        # Third-Party
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
            id="a1",
            name="ag",
            slug="ag",
            endpoint_url="https://example.com",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            enabled=True,
            version=1,
            visibility="public",
            team_id=None,
            owner_email=None,
            passthrough_headers=None,
            oauth_config=None,
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
                mock_db,
                "a1",
                update,
                modified_by="user",
                modified_from_ip="1.2.3.4",
                modified_via="api",
                modified_user_agent="test/1.0",
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
        # Third-Party
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
            with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
                mock_settings.insecure_allow_queryparam_auth = False
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                update = A2AAgentUpdate.model_construct(
                    auth_type="query_param",
                    auth_query_param_key="k",
                    auth_query_param_value="v",
                )
                with pytest.raises(A2AAgentError, match="Failed to update"):
                    await service.update_agent(mock_db, "a1", update)

    async def test_queryparam_host_not_allowed_on_update(self, service, mock_db, monkeypatch):
        """Host allowlist is enforced when switching to query_param."""
        agent = self._make_agent(auth_type="bearer", endpoint_url="https://bad.host.com/agent")
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = ["safe.host.com"]
                update = A2AAgentUpdate.model_construct(
                    auth_type="query_param",
                    auth_query_param_key="k",
                    auth_query_param_value="v",
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
            id="a1",
            name="secret",
            enabled=True,
            endpoint_url="https://x.com",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="private",
            team_id="t1",
            owner_email="other@x.com",
            agent_type="generic",
            protocol_version="1.0",
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
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/",
            auth_type="authheaders",
            auth_value={"X-Key": "val"},
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
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/custom",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="custom",
            protocol_version="2.0",
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
            agent_type="generic",
            protocol_version="1.0",
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
            agent_type="generic",
            protocol_version="1.0",
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
            agent_type="generic",
            protocol_version="1.0",
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
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/api",
            auth_type="query_param",
            auth_value=None,
            auth_query_params={"api_key": "encrypted_blob"},
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda x: {"api_key": "secret123"})
        monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", lambda url, params: url + "?api_key=secret123")
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
    async def test_invoke_query_param_error_redacts_secret_from_message(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Error messages from failed invocations must redact query param auth values."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=500, text="Internal error at https://x.com/api?api_key=secret123")
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/api",
            auth_type="query_param",
            auth_value=None,
            auth_query_params={"api_key": "encrypted_blob"},
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda x: {"api_key": "secret123"})
        monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", lambda url, params: url + "?api_key=secret123")
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        with pytest.raises(A2AAgentError) as exc_info:
            await service.invoke_agent(mock_db, "ag", {})
        assert "secret123" not in str(exc_info.value)
        assert "REDACTED" in str(exc_info.value) or "api_key" not in str(exc_info.value)

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_query_param_auth_decrypt_error_fails_closed(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Query-param decrypt failures must fail the invocation, not silently drop the credential.

        Sending the request without the credential can reach the agent as an
        unauthenticated call with unpredictable results; we require fail-closed
        semantics matching the header auth path.
        """
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/api",
            auth_type="query_param",
            auth_value=None,
            auth_query_params={"api_key": "bad"},  # pragma: allowlist secret
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _x: (_ for _ in ()).throw(ValueError("bad auth")))
        mock_apply = MagicMock()
        monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", mock_apply)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        with pytest.raises(A2AAgentError, match="query_param"):
            await service.invoke_agent(mock_db, "ag", {})
        mock_client.post.assert_not_called()
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
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/",
            auth_type="authheaders",
            auth_value={"X-API-Key": "secret"},
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

        result = await service.invoke_agent(mock_db, "ag", {})
        assert result["ok"] is True
        headers_used = mock_client.post.call_args.kwargs["headers"]
        assert headers_used.get("X-API-Key") == "secret"

    async def test_invoke_auth_value_decode_failure_raises(self, service, mock_db, monkeypatch):
        """decode_auth failures for auth_value raise A2AAgentError."""
        agent = SimpleNamespace(
            id="a1",
            name="ag",
            enabled=True,
            endpoint_url="https://x.com/",
            auth_type="basic",
            auth_value="bad",
            auth_query_params=None,
            visibility="public",
            team_id=None,
            owner_email=None,
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _x: (_ for _ in ()).throw(ValueError("bad")))

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
            agent_type="generic",
            protocol_version="1.0",
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
    async def test_invoke_query_uses_v1_send_message_payload(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Default query invocations should use A2A v1 SendMessage payloads for v1 agents."""
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
            agent_type="generic",
            protocol_version="1.0.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        await service.invoke_agent(mock_db, "ag", {"query": "hello"})
        outbound_json = mock_client.post.call_args.kwargs["json"]
        outbound_headers = mock_client.post.call_args.kwargs["headers"]

        assert outbound_json["method"] == "SendMessage"
        assert outbound_json["params"]["message"]["role"] == "ROLE_USER"
        assert outbound_json["params"]["message"]["parts"] == [{"text": "hello"}]
        assert "kind" not in outbound_json["params"]["message"]
        assert outbound_headers["A2A-Version"] == "1.0"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_invoke_delegates_to_rust_runtime_when_enabled(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """A2A invocations should delegate to the Rust runtime when explicitly enabled."""
        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock(return_value={"status_code": 200, "json": {"ok": True}, "text": ""})

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
            agent_type="generic",
            protocol_version="1.0.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_rust_a2a_runtime_client", lambda: rust_runtime)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_enabled", True)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_delegate_enabled", True)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        result = await service.invoke_agent(mock_db, "ag", {"query": "hello"})

        assert result == {"ok": True}
        rust_runtime.invoke.assert_called_once()
        mock_get_client.assert_not_called()

    async def test_get_agent_card_returns_none_when_agent_missing(self, service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        assert service.get_agent_card(mock_db, "missing") is None

    async def test_get_agent_card_builds_capabilities(self, service, mock_db):
        agent = SimpleNamespace(
            name="ag",
            description="desc",
            endpoint_url="https://x.com",
            version=2,
            protocol_version="1.0",
            capabilities={"streaming": True, "pushNotifications": True, "stateTransitionHistory": False, "skills": [{"id": "s1"}]},
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent

        result = service.get_agent_card(mock_db, "ag")

        assert result["name"] == "ag"
        assert result["capabilities"]["streaming"] is True
        assert result["capabilities"]["pushNotifications"] is True
        assert result["skills"] == [{"id": "s1"}]

    async def test_invoke_prepare_failure_without_auth_wraps_error(self, service, mock_db, monkeypatch):
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
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.prepare_a2a_invocation", lambda **_kw: (_ for _ in ()).throw(ValueError("bad prep")))

        with pytest.raises(A2AAgentError, match="Failed to prepare A2A invocation"):
            await service.invoke_agent(mock_db, "ag", {})

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    async def test_invoke_rust_runtime_error_wraps_agent_error(self, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
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
            agent_type="generic",
            protocol_version="1.0",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_enabled", True)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_delegate_enabled", True)

        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock(side_effect=RustA2ARuntimeError("runtime failed"))
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_rust_a2a_runtime_client", lambda: rust_runtime)

        mock_fresh_db.return_value.__enter__.return_value = MagicMock()
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()

        with pytest.raises(A2AAgentError, match="runtime failed"):
            await service.invoke_agent(mock_db, "ag", {})

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    async def test_invoke_persists_task_from_status_object(self, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
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
            agent_type="generic",
            protocol_version="1.0",
        )
        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock(
            return_value={
                "status_code": 200,
                "json": {"result": {"id": "task-1", "status": {"state": "working", "message": {"role": "agent"}}, "history": [1], "artifacts": [2]}},
                "text": "",
            }
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_rust_a2a_runtime_client", lambda: rust_runtime)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_enabled", True)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_delegate_enabled", True)
        mock_fresh_db.return_value.__enter__.return_value = MagicMock()
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()
        service.upsert_task = MagicMock(return_value={})

        result = await service.invoke_agent(mock_db, "ag", {})

        assert result["result"]["id"] == "task-1"
        service.upsert_task.assert_called_once()

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    async def test_invoke_task_persistence_failure_rolls_back(self, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
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
            agent_type="generic",
            protocol_version="1.0",
        )
        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock(return_value={"status_code": 200, "json": {"result": {"id": "task-1", "status": {"state": "working"}}}, "text": ""})

        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        mock_db.rollback = MagicMock()
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_rust_a2a_runtime_client", lambda: rust_runtime)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_enabled", True)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_delegate_enabled", True)
        mock_fresh_db.return_value.__enter__.return_value = MagicMock()
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()
        service.upsert_task = MagicMock(side_effect=RuntimeError("persist failed"))

        result = await service.invoke_agent(mock_db, "ag", {})

        assert result["result"]["id"] == "task-1"
        mock_db.rollback.assert_called_once()


class TestA2AInvalidationBestEffort:
    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def sample_agent_create(self):
        return A2AAgentCreate(
            name="test-agent",
            description="desc",
            endpoint_url="https://example.com/agent",
            agent_type="generic",
            protocol_version="1.0",
            capabilities={},
            config={},
            tags=[],
        )

    @pytest.fixture
    def sample_db_agent(self):
        return SimpleNamespace(
            id="agent-1",
            name="test-agent",
            slug="test-agent",
            endpoint_url="https://example.com/agent",
            description="desc",
            enabled=True,
            version=1,
            visibility="public",
            team_id=None,
            owner_email=None,
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            protocol_version="1.0",
            agent_type="generic",
            tool_id=None,
            metrics=[],
        )

    async def test_register_agent_ignores_runtime_error_from_invalidation(self, service, mock_db, sample_agent_create, monkeypatch):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.add = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")), patch("mcpgateway.schemas.ToolRead.model_validate", return_value=MagicMock()):
            await service.register_agent(mock_db, sample_agent_create)

    async def test_update_agent_ignores_generic_invalidation_error(self, service, mock_db, sample_db_agent, monkeypatch):
        sample_db_agent.version = 1
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        loop = MagicMock()
        loop.create_task.side_effect = Exception("boom")
        with patch("asyncio.get_running_loop", return_value=loop), patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_db_agent):
            with patch.object(service, "convert_agent_to_read", return_value=MagicMock()):
                await service.update_agent(mock_db, sample_db_agent.id, A2AAgentUpdate(description="Updated description"))

    async def test_delete_agent_ignores_generic_invalidation_error(self, service, mock_db, sample_db_agent, monkeypatch):
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()
        loop = MagicMock()
        loop.create_task.side_effect = Exception("boom")
        with patch("asyncio.get_running_loop", return_value=loop):
            await service.delete_agent(mock_db, sample_db_agent.id)


class TestA2ATaskWireAndUpsert:
    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def test_task_to_wire_prefers_latest_message_and_payload(self, service):
        task = SimpleNamespace(
            task_id="t1",
            context_id="ctx",
            state="working",
            latest_message={"role": "agent", "parts": [{"text": "hi"}]},
            last_error=None,
            payload={"history": [1], "artifacts": [2]},
        )

        result = service._task_to_wire(task)

        assert result["status"]["message"] == {"role": "agent", "parts": [{"text": "hi"}]}
        assert result["history"] == [1]
        assert result["artifacts"] == [2]

    def test_task_to_wire_uses_last_error_for_failed_tasks(self, service):
        task = SimpleNamespace(task_id="t1", context_id=None, state="failed", latest_message=None, last_error="boom", payload=None)

        result = service._task_to_wire(task)

        assert result["status"]["message"]["parts"][0]["text"] == "boom"

    def test_upsert_task_creates_and_marks_completed(self, service, mock_db):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        result = service.upsert_task(
            mock_db,
            "agent-1",
            "task-1",
            "completed",
            context_id="ctx",
            latest_message={"role": "agent"},
            payload={"history": [1]},
            last_error="ignored",
        )

        assert result["id"] == "task-1"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()


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
            _result = service.convert_agent_to_read(agent, db=mock_db)
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
            _result = service.convert_agent_to_read(agent, include_metrics=True)

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
        # First-Party
        from mcpgateway.schemas import A2AAgentAggregateMetrics

        cached_dict = {
            "total_agents": 5,
            "active_agents": 3,
            "total_interactions": 100,
            "successful_interactions": 90,
            "failed_interactions": 10,
            "success_rate": 90.0,
            "avg_response_time": 1.5,
            "min_response_time": 0.5,
            "max_response_time": 3.0,
        }

        monkeypatch.setattr("mcpgateway.cache.metrics_cache.is_cache_enabled", lambda: True)
        monkeypatch.setattr(
            "mcpgateway.cache.metrics_cache.metrics_cache",
            SimpleNamespace(
                get=MagicMock(return_value=cached_dict),
            ),
        )

        result = await service.aggregate_metrics(mock_db)
        assert isinstance(result, A2AAgentAggregateMetrics)
        assert result.total_agents == 5
        assert result.active_agents == 3

    async def test_cache_write(self, service, mock_db, monkeypatch):
        """Computed metrics are written to cache."""
        # First-Party
        from mcpgateway.schemas import A2AAgentAggregateMetrics
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        mock_metrics = AggregatedMetrics(
            total_executions=10,
            successful_executions=8,
            failed_executions=2,
            failure_rate=0.2,
            min_response_time=0.1,
            max_response_time=2.0,
            avg_response_time=1.0,
            last_execution_time=None,
            raw_count=10,
            rollup_count=0,
        )

        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # cache miss
        mock_cache.set = MagicMock()

        monkeypatch.setattr("mcpgateway.cache.metrics_cache.is_cache_enabled", lambda: True)
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", mock_cache)
        monkeypatch.setattr("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", lambda db, t: mock_metrics)

        # Mock agent counts via a2a_stats_cache (avoids singleton cache interference)
        monkeypatch.setattr("mcpgateway.cache.a2a_stats_cache.a2a_stats_cache.get_counts", lambda db: {"total": 3, "active": 2})

        result = await service.aggregate_metrics(mock_db)
        assert isinstance(result, A2AAgentAggregateMetrics)
        assert result.total_agents == 3
        assert result.active_agents == 2
        assert result.total_interactions == 10
        mock_cache.set.assert_called_once()

    async def test_cache_non_dict_falls_through(self, service, mock_db, monkeypatch):
        """Non-dict cached value (e.g. list from leaked mock) is ignored and metrics are recomputed."""
        # First-Party
        from mcpgateway.schemas import A2AAgentAggregateMetrics
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        mock_metrics = AggregatedMetrics(
            total_executions=7,
            successful_executions=6,
            failed_executions=1,
            failure_rate=round(1 / 7, 4),
            min_response_time=0.2,
            max_response_time=1.5,
            avg_response_time=0.8,
            last_execution_time=None,
            raw_count=7,
            rollup_count=0,
        )

        mock_cache = MagicMock()
        mock_cache.get.return_value = [1, 2, 3]  # Non-dict: should be skipped
        mock_cache.set = MagicMock()

        monkeypatch.setattr("mcpgateway.cache.metrics_cache.is_cache_enabled", lambda: True)
        monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache", mock_cache)
        monkeypatch.setattr("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", lambda db, t: mock_metrics)
        monkeypatch.setattr("mcpgateway.cache.a2a_stats_cache.a2a_stats_cache.get_counts", lambda db: {"total": 4, "active": 3})

        result = await service.aggregate_metrics(mock_db)
        assert isinstance(result, A2AAgentAggregateMetrics)
        assert result.total_agents == 4
        assert result.total_interactions == 7
        mock_cache.set.assert_called_once()


class TestListAgentsCacheAttributeError:
    """Cover list_agents AttributeError branch when cache set fails (line 721-722)."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_cache_set_attribute_error_skipped(self, service, mock_db, monkeypatch):
        """AttributeError during cache set is silently ignored."""
        # Return an object without model_dump to trigger AttributeError
        agent = SimpleNamespace(id="a1", team_id=None, visibility="public")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [agent]
        mock_db.execute.return_value.all.return_value = []
        mock_db.commit = MagicMock()

        service.convert_agent_to_read = MagicMock(return_value=SimpleNamespace(no_model_dump=True))
        cache = SimpleNamespace(
            hash_filters=MagicMock(return_value="h"),
            get=AsyncMock(return_value=None),
            set=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: cache)

        # Should not raise even though result objects lack model_dump
        result, cursor = await service.list_agents(mock_db)
        assert len(result) == 1


class TestUpdateAgentQueryParamAuth:
    """Cover update_agent query_param auth branches (lines 1052-1053, 1086-1128)."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def _make_agent(self, **overrides):
        defaults = dict(
            id="a1",
            name="ag",
            slug="ag",
            endpoint_url="https://example.com",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            enabled=True,
            version=1,
            visibility="public",
            team_id=None,
            owner_email=None,
            passthrough_headers=None,
            oauth_config=None,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    async def test_switching_away_from_queryparam_clears_params(self, service, mock_db, monkeypatch):
        """Switching from query_param to bearer clears auth_query_params (lines 1051-1053)."""
        agent = self._make_agent(auth_type="query_param", auth_query_params={"api_key": "encrypted"})
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with patch("mcpgateway.services.tool_service.tool_service") as ts:
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)
                update = A2AAgentUpdate.model_construct(auth_type="bearer", auth_value="new-token")
                await service.update_agent(mock_db, "a1", update)

        assert agent.auth_query_params is None

    async def test_switching_to_queryparam_with_new_value(self, service, mock_db, monkeypatch):
        """Switching to query_param with key+value encrypts and stores (lines 1086-1111, 1126-1128)."""
        agent = self._make_agent(auth_type="bearer", auth_value="old-token")
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with (
                patch("mcpgateway.services.a2a_service.settings") as mock_settings,
                patch("mcpgateway.services.tool_service.tool_service") as ts,
            ):
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)

                update = A2AAgentUpdate.model_construct(
                    auth_type="query_param",
                    auth_query_param_key="api_key",
                    auth_query_param_value="secret123",
                )
                await service.update_agent(mock_db, "a1", update)

        assert agent.auth_type == "query_param"
        assert agent.auth_value is None
        assert agent.auth_query_params is not None
        assert "api_key" in agent.auth_query_params

    async def test_updating_queryparam_value_only_rotation(self, service, mock_db, monkeypatch):
        """Updating value without key reuses existing key (lines 1089-1092)."""
        agent = self._make_agent(
            auth_type="query_param",
            auth_query_params={"existing_key": encode_auth({"existing_key": "old_value"})},
        )
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with (
                patch("mcpgateway.services.a2a_service.settings") as mock_settings,
                patch("mcpgateway.services.tool_service.tool_service") as ts,
            ):
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)

                # Only value provided, no key — should reuse "existing_key"
                update = A2AAgentUpdate.model_construct(
                    auth_query_param_key=None,
                    auth_query_param_value="new_value",
                )
                await service.update_agent(mock_db, "a1", update)

        assert agent.auth_query_params is not None
        assert "existing_key" in agent.auth_query_params

    async def test_updating_queryparam_masked_value_same_key(self, service, mock_db, monkeypatch):
        """Masked placeholder value with same key preserves existing encrypted value (line 1112)."""
        agent = self._make_agent(
            auth_type="query_param",
            auth_query_params={"api_key": encode_auth({"api_key": "real_secret"})},
        )
        original_params = dict(agent.auth_query_params)

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with (
                patch("mcpgateway.services.a2a_service.settings") as mock_settings,
                patch("mcpgateway.services.tool_service.tool_service") as ts,
            ):
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                mock_settings.masked_auth_value = "****"
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)

                # SecretStr-like value that returns the masked placeholder
                masked_value = MagicMock()
                masked_value.get_secret_value.return_value = "****"
                update = A2AAgentUpdate.model_construct(
                    auth_query_param_key="api_key",
                    auth_query_param_value=masked_value,
                )
                await service.update_agent(mock_db, "a1", update)

        # Params unchanged because key is the same and value was masked
        assert agent.auth_query_params == original_params

    async def test_updating_queryparam_masked_value_different_key(self, service, mock_db, monkeypatch):
        """Masked value with changed key re-encrypts under new key (lines 1115-1123)."""
        agent = self._make_agent(
            auth_type="query_param",
            auth_query_params={"old_key": encode_auth({"old_key": "real_secret"})},
        )

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with (
                patch("mcpgateway.services.a2a_service.settings") as mock_settings,
                patch("mcpgateway.services.tool_service.tool_service") as ts,
            ):
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                mock_settings.masked_auth_value = "****"
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)

                masked_value = MagicMock()
                masked_value.get_secret_value.return_value = "****"
                update = A2AAgentUpdate.model_construct(
                    auth_query_param_key="new_key",
                    auth_query_param_value=masked_value,
                )
                await service.update_agent(mock_db, "a1", update)

        # Key should have changed
        assert "new_key" in agent.auth_query_params
        assert "old_key" not in agent.auth_query_params

    async def test_updating_queryparam_no_value_provided(self, service, mock_db, monkeypatch):
        """Key provided without value results in raw_value=None, no update (lines 1105-1106)."""
        agent = self._make_agent(
            auth_type="query_param",
            auth_query_params={"api_key": encode_auth({"api_key": "real_secret"})},
        )
        original_params = dict(agent.auth_query_params)

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with (
                patch("mcpgateway.services.a2a_service.settings") as mock_settings,
                patch("mcpgateway.services.tool_service.tool_service") as ts,
            ):
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)

                update = A2AAgentUpdate.model_construct(
                    auth_query_param_key="api_key",
                    auth_query_param_value=None,
                )
                await service.update_agent(mock_db, "a1", update)

        # No change since raw_value was None
        assert agent.auth_query_params == original_params

    async def test_queryparam_string_value(self, service, mock_db, monkeypatch):
        """Plain string value (no get_secret_value) is used directly (lines 1103-1104)."""
        agent = self._make_agent(auth_type="query_param", auth_query_params={"api_key": "old"})
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            service.convert_agent_to_read = MagicMock(return_value=MagicMock())

            dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
            monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
            monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))

            with (
                patch("mcpgateway.services.a2a_service.settings") as mock_settings,
                patch("mcpgateway.services.tool_service.tool_service") as ts,
            ):
                mock_settings.insecure_allow_queryparam_auth = True
                mock_settings.insecure_queryparam_auth_allowed_hosts = []
                ts.update_tool_from_a2a_agent = AsyncMock(return_value=None)

                # Plain string, not a SecretStr
                update = A2AAgentUpdate.model_construct(
                    auth_query_param_key="api_key",
                    auth_query_param_value="new_plain_value",
                )
                await service.update_agent(mock_db, "a1", update)

        assert agent.auth_query_params is not None
        assert "api_key" in agent.auth_query_params


class TestSetAgentStateToolCascade:
    """Cover set_agent_state tool cascade branches (lines 1236-1240)."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    async def test_cascade_deactivates_tool(self, service, mock_db, monkeypatch):
        """Deactivating agent with tool_id cascades to tool (lines 1236-1240)."""
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, tool_id="t1", tool=SimpleNamespace(name="my-tool", gateway_id="gw1"))
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        tool_update_result = MagicMock()
        tool_update_result.rowcount = 1
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=agent)),
            tool_update_result,
        ]
        mock_db.execute.side_effect = execute_results

        dummy_cache = SimpleNamespace(
            invalidate_agents=AsyncMock(),
            invalidate_tools=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)

        dummy_tool_lookup_cache = SimpleNamespace(invalidate=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_tool_lookup_cache", lambda: dummy_tool_lookup_cache)

        await service.set_agent_state(mock_db, "a1", activate=False)

        assert agent.enabled is False
        assert mock_db.execute.call_count == 2
        dummy_cache.invalidate_tools.assert_awaited_once()
        dummy_tool_lookup_cache.invalidate.assert_awaited_once_with("my-tool", gateway_id="gw1")

    async def test_cascade_activates_tool(self, service, mock_db, monkeypatch):
        """Activating agent with tool_id cascades to tool."""
        agent = SimpleNamespace(id="a1", enabled=False, name="ag", reachable=True, tool_id="t1", tool=SimpleNamespace(name="my-tool", gateway_id="gw1"))
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        tool_update_result = MagicMock()
        tool_update_result.rowcount = 1
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=agent)),
            tool_update_result,
        ]
        mock_db.execute.side_effect = execute_results

        dummy_cache = SimpleNamespace(
            invalidate_agents=AsyncMock(),
            invalidate_tools=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)

        dummy_tool_lookup_cache = SimpleNamespace(invalidate=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_tool_lookup_cache", lambda: dummy_tool_lookup_cache)

        await service.set_agent_state(mock_db, "a1", activate=True)

        assert agent.enabled is True
        dummy_cache.invalidate_tools.assert_awaited_once()
        dummy_tool_lookup_cache.invalidate.assert_awaited_once_with("my-tool", gateway_id="gw1")

    async def test_cascade_deactivates_tool_no_gateway_id(self, service, mock_db, monkeypatch):
        """Deactivating agent with tool that has no gateway_id passes gateway_id=None."""
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, tool_id="t1", tool=SimpleNamespace(name="my-tool", gateway_id=None))
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        tool_update_result = MagicMock()
        tool_update_result.rowcount = 1
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=agent)),
            tool_update_result,
        ]
        mock_db.execute.side_effect = execute_results

        dummy_cache = SimpleNamespace(
            invalidate_agents=AsyncMock(),
            invalidate_tools=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)

        dummy_tool_lookup_cache = SimpleNamespace(invalidate=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_tool_lookup_cache", lambda: dummy_tool_lookup_cache)

        await service.set_agent_state(mock_db, "a1", activate=False)

        assert agent.enabled is False
        dummy_tool_lookup_cache.invalidate.assert_awaited_once_with("my-tool", gateway_id=None)

    async def test_cascade_no_tool_id_skips_update(self, service, mock_db, monkeypatch):
        """Agent without tool_id skips tool cascade."""
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, tool_id=None, tool=None)
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        dummy_cache = SimpleNamespace(
            invalidate_agents=AsyncMock(),
            invalidate_tools=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)

        await service.set_agent_state(mock_db, "a1", activate=False)

        assert mock_db.execute.call_count == 1  # Only agent lookup
        dummy_cache.invalidate_tools.assert_not_awaited()

    async def test_cascade_tool_already_matching_no_commit(self, service, mock_db, monkeypatch):
        """Tool already in desired state — rowcount=0, no extra commit or cache invalidation."""
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, tool_id="t1", tool=SimpleNamespace(name="my-tool"))
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        tool_update_result = MagicMock()
        tool_update_result.rowcount = 0
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=agent)),
            tool_update_result,
        ]
        mock_db.execute.side_effect = execute_results

        dummy_cache = SimpleNamespace(
            invalidate_agents=AsyncMock(),
            invalidate_tools=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)

        await service.set_agent_state(mock_db, "a1", activate=False)

        assert mock_db.execute.call_count == 2
        dummy_cache.invalidate_tools.assert_not_awaited()

    async def test_cascade_tool_update_failure_propagates(self, service, mock_db, monkeypatch):
        """Tool cascade failure propagates to caller (matches gateway_service pattern)."""
        agent = SimpleNamespace(id="a1", enabled=True, name="ag", reachable=True, tool_id="t1", tool=SimpleNamespace(name="my-tool"))

        # First call returns agent, second call (tool UPDATE) raises
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=agent)),
        ]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return execute_results[0]
            raise RuntimeError("DB write failed")

        mock_db.execute.side_effect = side_effect
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())

        dummy_cache = SimpleNamespace(
            invalidate_agents=AsyncMock(),
            invalidate_tools=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)

        with pytest.raises(RuntimeError, match="DB write failed"):
            await service.set_agent_state(mock_db, "a1", activate=False)


# ---------------------------------------------------------------------------
# New method coverage tests
# ---------------------------------------------------------------------------


class TestCancelTask:
    """Unit tests for A2AAgentService.cancel_task."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def _make_task(self, state: str = "submitted"):
        task = MagicMock()
        task.task_id = "task-1"
        task.a2a_agent_id = "agent-1"
        task.state = state
        task.completed_at = None
        task.context_id = None
        task.latest_message = None
        task.last_error = None
        task.payload = None
        return task

    @staticmethod
    def _mock_task_query(task):
        """Build a mock query that behaves like ``.limit(2).all() → [task]``."""
        q = MagicMock()
        q.filter.return_value = q
        q.limit.return_value = q
        q.all.return_value = [task] if task is not None else []
        return q

    def test_cancel_active_task(self, service, mock_db):
        """Task found in non-terminal state is set to canceled and returned as wire dict."""
        task = self._make_task("submitted")
        mock_db.query.return_value = self._mock_task_query(task)
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        result = service.cancel_task(mock_db, "task-1")

        assert task.state == "canceled"
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(task)
        assert result["id"] == "task-1"
        assert result["status"]["state"] == "canceled"

    def test_cancel_already_terminal_task(self, service, mock_db):
        """Task already in terminal state is returned as-is without modification."""
        task = self._make_task("completed")
        mock_db.query.return_value = self._mock_task_query(task)

        result = service.cancel_task(mock_db, "task-1")

        assert task.state == "completed"
        mock_db.commit.assert_not_called()
        assert result["id"] == "task-1"
        assert result["status"]["state"] == "completed"

    def test_cancel_task_not_found_returns_none(self, service, mock_db):
        """Returns None when the task does not exist."""
        mock_db.query.return_value = self._mock_task_query(None)

        result = service.cancel_task(mock_db, "missing-task")

        assert result is None

    def test_cancel_task_with_agent_id_filter(self, service, mock_db):
        """agent_id parameter adds an extra filter clause."""
        task = self._make_task("submitted")
        mock_query = self._mock_task_query(task)
        mock_db.query.return_value = mock_query
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        service.cancel_task(mock_db, "task-1", agent_id="agent-1")

        # filter called: task_id, agent_id, and agent visibility lookup
        assert mock_query.filter.call_count >= 2

    def test_cancel_ambiguous_task_without_agent_id_returns_none(self, service, mock_db):
        """Two rows with the same ``task_id`` and no ``agent_id`` filter must refuse to guess."""
        task_a = self._make_task("submitted")
        task_a.a2a_agent_id = "agent-a"
        task_b = self._make_task("submitted")
        task_b.a2a_agent_id = "agent-b"

        q = MagicMock()
        q.filter.return_value = q
        q.limit.return_value = q
        q.all.return_value = [task_a, task_b]
        mock_db.query.return_value = q

        result = service.cancel_task(mock_db, "shared-task-id")
        assert result is None
        # task_a must not have been cancelled by a "first match wins" policy.
        assert task_a.state == "submitted"
        assert task_b.state == "submitted"

    def _setup_task_and_agent(self, mock_db, task, agent):
        """Wire mock_db.query() to return task on first call and agent on second."""
        mock_task_q = self._mock_task_query(task)
        mock_agent_q = MagicMock()
        mock_agent_q.filter.return_value = mock_agent_q
        mock_agent_q.first.return_value = agent
        mock_db.query.side_effect = [mock_task_q, mock_agent_q]

    def test_cancel_task_hidden_from_wrong_team(self, service, mock_db):
        """Team-scoped user cannot cancel tasks on a different team's agent."""
        task = self._make_task("submitted")
        agent = MagicMock()
        agent.visibility = "team"
        agent.team_id = "team-b"
        agent.owner_email = "other@test.com"
        self._setup_task_and_agent(mock_db, task, agent)

        result = service.cancel_task(mock_db, "task-1", user_email="user@test.com", token_teams=["team-a"])
        assert result is None

    def test_cancel_task_admin_bypass(self, service, mock_db):
        """Admin can cancel any task regardless of visibility."""
        task = self._make_task("submitted")
        agent = MagicMock()
        agent.visibility = "private"
        agent.owner_email = "other@test.com"
        self._setup_task_and_agent(mock_db, task, agent)
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        result = service.cancel_task(mock_db, "task-1", user_email=None, token_teams=None)
        assert result is not None
        assert result["status"]["state"] == "canceled"

    def test_cancel_task_public_only_user_denied_for_private(self, service, mock_db):
        """Public-only user (empty teams) cannot cancel private agent tasks."""
        task = self._make_task("submitted")
        agent = MagicMock()
        agent.visibility = "private"
        agent.owner_email = "user@test.com"
        self._setup_task_and_agent(mock_db, task, agent)

        result = service.cancel_task(mock_db, "task-1", user_email="user@test.com", token_teams=[])
        assert result is None


class TestPushConfigCRUD:
    """Unit tests for push notification config CRUD methods."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def _config_data(self):
        return {
            "a2a_agent_id": "agent-1",
            "task_id": "task-1",
            "webhook_url": "https://example.com/webhook",
            "auth_token": "secret-token",
            "events": ["state_change"],
            "enabled": True,
        }

    def test_create_push_config(self, service, mock_db):
        """create_push_config adds a record and returns a dict."""
        # The duplicate-check query must return None so the insert path runs.
        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = None
        mock_db.query.return_value = mock_dup_query
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        expected = {"id": "cfg-1", "task_id": "task-1"}
        with (
            patch("mcpgateway.db.A2APushNotificationConfig") as mock_model,
            patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv,
        ):
            cfg_instance = MagicMock()
            mock_model.return_value = cfg_instance
            mock_mv.return_value.model_dump.return_value = expected

            result = service.create_push_config(mock_db, self._config_data())

        mock_db.add.assert_called_once_with(cfg_instance)
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(cfg_instance)
        assert result == expected

    def test_create_push_config_idempotent_retry_is_noop(self, service, mock_db):
        """Re-registering the exact same config is an idempotent no-op.

        ``updated_at`` must NOT be bumped — neither commit nor refresh is
        called when none of the mutable fields differ.
        """
        # First-Party
        from mcpgateway.utils.services_auth import encode_auth

        existing_cfg = MagicMock()
        existing_cfg.auth_token = encode_auth({"token": "secret-token"})  # pragma: allowlist secret
        existing_cfg.events = ["state_change"]
        existing_cfg.enabled = True

        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = existing_cfg
        mock_db.query.return_value = mock_dup_query
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        expected = {"id": "cfg-existing", "task_id": "task-1"}
        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = expected
            result = service.create_push_config(mock_db, self._config_data())

        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()
        mock_db.refresh.assert_not_called()
        assert result == expected

    def test_create_push_config_upserts_rotated_auth_token(self, service, mock_db):
        """Re-registering with a rotated bearer secret must update the stored token.

        This is the security fix: previously the stale row was returned
        verbatim so a client attempting to rotate a leaked secret would
        silently keep dispatching with the old one.
        """
        # First-Party
        from mcpgateway.utils.services_auth import decode_auth, encode_auth

        existing_cfg = MagicMock()
        existing_cfg.auth_token = encode_auth({"token": "old-token"})  # pragma: allowlist secret
        existing_cfg.events = ["state_change"]
        existing_cfg.enabled = True

        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = existing_cfg
        mock_db.query.return_value = mock_dup_query
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        rotated = self._config_data()
        rotated["auth_token"] = "new-token"  # pragma: allowlist secret

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {"id": "cfg-existing"}
            service.create_push_config(mock_db, rotated)

        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(existing_cfg)
        assert decode_auth(existing_cfg.auth_token) == {"token": "new-token"}  # pragma: allowlist secret

    def test_create_push_config_upserts_changed_events_and_enabled(self, service, mock_db):
        """Re-registering with a narrowed event set or enabled=False must apply."""
        # First-Party
        from mcpgateway.utils.services_auth import encode_auth

        existing_cfg = MagicMock()
        existing_cfg.auth_token = encode_auth({"token": "secret-token"})  # pragma: allowlist secret
        existing_cfg.events = ["completed", "failed"]
        existing_cfg.enabled = True

        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = existing_cfg
        mock_db.query.return_value = mock_dup_query
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        updated = self._config_data()
        updated["events"] = ["completed"]
        updated["enabled"] = False

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {"id": "cfg-existing"}
            service.create_push_config(mock_db, updated)

        mock_db.commit.assert_called_once()
        assert existing_cfg.events == ["completed"]
        assert existing_cfg.enabled is False

    def test_create_push_config_upserts_when_existing_ciphertext_is_undecryptable(self, service, mock_db):
        """Legacy cleartext or rotated-key ciphertext must be replaced with fresh ciphertext."""
        # First-Party
        from mcpgateway.utils.services_auth import decode_auth

        existing_cfg = MagicMock()
        existing_cfg.auth_token = "legacy-cleartext-or-rotated-ciphertext"  # pragma: allowlist secret
        existing_cfg.events = ["state_change"]
        existing_cfg.enabled = True

        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = existing_cfg
        mock_db.query.return_value = mock_dup_query
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {"id": "cfg-existing"}
            service.create_push_config(mock_db, self._config_data())

        mock_db.commit.assert_called_once()
        assert decode_auth(existing_cfg.auth_token) == {"token": "secret-token"}  # pragma: allowlist secret

    def test_create_push_config_upserts_add_token_to_previously_unauthenticated(self, service, mock_db):
        """None → Some: adding a bearer token to a previously-unsecured webhook."""
        # First-Party
        from mcpgateway.utils.services_auth import decode_auth

        existing_cfg = MagicMock()
        existing_cfg.auth_token = None
        existing_cfg.events = ["state_change"]
        existing_cfg.enabled = True

        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = existing_cfg
        mock_db.query.return_value = mock_dup_query
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {"id": "cfg-existing"}
            service.create_push_config(mock_db, self._config_data())

        mock_db.commit.assert_called_once()
        assert existing_cfg.auth_token is not None, "token must be set"
        assert decode_auth(existing_cfg.auth_token) == {"token": "secret-token"}  # pragma: allowlist secret

    def test_create_push_config_upserts_remove_token_with_decryptable_existing(self, service, mock_db):
        """Some → None: caller rotates the token away (set auth_token=None)."""
        # First-Party
        from mcpgateway.utils.services_auth import encode_auth

        existing_cfg = MagicMock()
        existing_cfg.auth_token = encode_auth({"token": "to-be-removed"})  # pragma: allowlist secret
        existing_cfg.events = ["state_change"]
        existing_cfg.enabled = True

        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = existing_cfg
        mock_db.query.return_value = mock_dup_query
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        data = self._config_data()
        data["auth_token"] = None  # explicit clear

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {"id": "cfg-existing"}
            service.create_push_config(mock_db, data)

        mock_db.commit.assert_called_once()
        assert existing_cfg.auth_token is None, "token must be cleared"

    def test_create_push_config_race_lost_branch_applies_upsert(self, service, mock_db):
        """If an IntegrityError loses the insert race, the winner row must still be upserted.

        Sequence: pre-check sees no row → INSERT → commit raises
        IntegrityError → rollback → re-find finds the racing winner →
        ``_apply_push_config_mutations`` runs against the winner.  This
        path was added as part of the upsert refactor; this test pins it.
        """
        # First-Party
        from mcpgateway.utils.services_auth import decode_auth, encode_auth

        winner_cfg = MagicMock()
        winner_cfg.auth_token = encode_auth({"token": "loser-token"})  # pragma: allowlist secret
        winner_cfg.events = ["state_change"]
        winner_cfg.enabled = True

        # First query: pre-check finds nothing.  Second query (after
        # rollback): re-find returns the racing winner.
        empty_query = MagicMock()
        empty_query.filter.return_value = empty_query
        empty_query.first.return_value = None
        winner_query = MagicMock()
        winner_query.filter.return_value = winner_query
        winner_query.first.return_value = winner_cfg

        mock_db.query.side_effect = [empty_query, winner_query]
        mock_db.add = MagicMock()
        # First commit raises (race lost); second commit (the upsert) succeeds.
        mock_db.commit = MagicMock(side_effect=[Exception("IntegrityError simulated"), None])
        mock_db.rollback = MagicMock()
        mock_db.refresh = MagicMock()

        rotated = self._config_data()
        rotated["auth_token"] = "winner-rotated-token"  # pragma: allowlist secret

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {"id": "winner"}
            service.create_push_config(mock_db, rotated)

        mock_db.rollback.assert_called_once()
        # The upsert must have actually run on the winner — token rotated.
        assert decode_auth(winner_cfg.auth_token) == {"token": "winner-rotated-token"}  # pragma: allowlist secret

    def test_create_push_config_upserts_remove_token_with_undecryptable_existing(self, service, mock_db):
        """Some(undecryptable) → None regression.

        If the existing ciphertext cannot be decrypted (rotated master key,
        corrupt row) AND the caller rotates to no-auth, the stale ciphertext
        must still be cleared.  A prior bug fell through this branch
        silently — the upsert would report success while leaving the
        un-decryptable ciphertext in place, so ``list_push_configs_for_dispatch``
        kept logging ``failed to decrypt`` on every dispatch.
        """
        existing_cfg = MagicMock()
        existing_cfg.auth_token = "corrupt-ciphertext"  # pragma: allowlist secret
        existing_cfg.events = ["state_change"]
        existing_cfg.enabled = True

        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = existing_cfg
        mock_db.query.return_value = mock_dup_query
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        data = self._config_data()
        data["auth_token"] = None  # explicit clear

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {"id": "cfg-existing"}
            service.create_push_config(mock_db, data)

        mock_db.commit.assert_called_once()
        assert existing_cfg.auth_token is None, "undecryptable ciphertext must be cleared"

    @staticmethod
    def _mock_push_query(rows):
        """Build a mock query that behaves like ``.order_by(...).limit(2).all() → rows``."""
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.all.return_value = list(rows)
        return q

    def test_get_push_config_found(self, service, mock_db):
        """get_push_config returns a dict when config exists."""
        cfg = MagicMock()
        mock_db.query.return_value = self._mock_push_query([cfg])

        expected = {"id": "cfg-1", "task_id": "task-1"}
        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = expected
            result = service.get_push_config(mock_db, "task-1")

        assert result == expected

    def test_get_push_config_not_found(self, service, mock_db):
        """get_push_config returns None when no config exists for the task."""
        mock_db.query.return_value = self._mock_push_query([])

        result = service.get_push_config(mock_db, "missing-task")

        assert result is None

    def test_get_push_config_ambiguous_without_agent_id_returns_none(self, service, mock_db):
        """Two rows with the same ``task_id`` and no ``agent_id`` filter must refuse to guess."""
        cfg_a = MagicMock()
        cfg_b = MagicMock()
        mock_db.query.return_value = self._mock_push_query([cfg_a, cfg_b])

        result = service.get_push_config(mock_db, "shared-task-id")
        assert result is None

    def test_get_push_config_with_agent_id(self, service, mock_db):
        """agent_id adds a second filter clause to get_push_config."""
        cfg = MagicMock()
        mock_query = self._mock_push_query([cfg])
        mock_db.query.return_value = mock_query

        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.return_value.model_dump.return_value = {}
            service.get_push_config(mock_db, "task-1", agent_id="agent-1")

        assert mock_query.filter.call_count == 2

    def test_list_push_configs_returns_list(self, service, mock_db):
        """list_push_configs returns a list of serialized config dicts."""
        cfg1 = MagicMock()
        cfg2 = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [cfg1, cfg2]
        mock_db.query.return_value = mock_query

        row1 = {"id": "c1", "task_id": "t1"}
        row2 = {"id": "c2", "task_id": "t2"}
        with patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv:
            mock_mv.side_effect = [
                MagicMock(model_dump=MagicMock(return_value=row1)),
                MagicMock(model_dump=MagicMock(return_value=row2)),
            ]
            result = service.list_push_configs(mock_db)

        assert result == [row1, row2]

    def test_list_push_configs_with_filters(self, service, mock_db):
        """list_push_configs applies agent_id and task_id filters."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        service.list_push_configs(mock_db, agent_id="agent-1", task_id="task-1")

        assert mock_query.filter.call_count == 2

    def test_delete_push_config_found(self, service, mock_db):
        """delete_push_config deletes the record and returns True."""
        cfg = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = cfg
        mock_db.query.return_value = mock_query
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()

        result = service.delete_push_config(mock_db, "cfg-1")

        mock_db.delete.assert_called_once_with(cfg)
        mock_db.commit.assert_called_once()
        assert result is True

    def test_delete_push_config_not_found(self, service, mock_db):
        """delete_push_config returns False when the config does not exist."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        result = service.delete_push_config(mock_db, "missing-cfg")

        mock_db.delete.assert_not_called()
        assert result is False

    def test_create_push_config_encrypts_auth_token_at_rest(self, service, mock_db):
        """Plaintext auth_token must be encrypted before being written to the DB.

        The bearer token that signs outbound webhook requests is sensitive
        and must not be recoverable from a raw DB dump or backup.
        """
        # First-Party
        from mcpgateway.utils.services_auth import decode_auth

        # No existing row → insert path.
        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = None
        mock_db.query.return_value = mock_dup_query
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        captured = {}

        def capture_init(**kwargs):
            captured.update(kwargs)
            stub = MagicMock()
            stub.auth_token = kwargs.get("auth_token")
            return stub

        with (
            patch("mcpgateway.db.A2APushNotificationConfig", side_effect=capture_init),
            patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv,
        ):
            mock_mv.return_value.model_dump.return_value = {}
            service.create_push_config(mock_db, self._config_data())

        stored = captured["auth_token"]
        assert stored != "secret-token", "auth_token must be ciphertext, not cleartext"  # pragma: allowlist secret
        # Round-trip via decode_auth proves it was encrypted (not, e.g.,
        # blanked out) and that the original value is recoverable for
        # webhook dispatch.
        decoded = decode_auth(stored)
        assert decoded == {"token": "secret-token"}  # pragma: allowlist secret

    def test_create_push_config_with_no_auth_token_stores_none(self, service, mock_db):
        """A missing/empty auth_token stays as NULL (not an empty ciphertext)."""
        mock_dup_query = MagicMock()
        mock_dup_query.filter.return_value = mock_dup_query
        mock_dup_query.first.return_value = None
        mock_db.query.return_value = mock_dup_query

        captured = {}

        def capture_init(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        data = self._config_data()
        data["auth_token"] = None
        with (
            patch("mcpgateway.db.A2APushNotificationConfig", side_effect=capture_init),
            patch("mcpgateway.schemas.A2APushNotificationConfigRead.model_validate") as mock_mv,
        ):
            mock_mv.return_value.model_dump.return_value = {}
            service.create_push_config(mock_db, data)

        assert captured["auth_token"] is None

    def test_list_push_configs_for_dispatch_decrypts_auth_token(self, service, mock_db):
        """Rust-facing dispatch listing must return the plaintext token."""
        # First-Party
        from mcpgateway.utils.services_auth import encode_auth

        cfg = MagicMock()
        cfg.id = "cfg-1"
        cfg.a2a_agent_id = "agent-1"
        cfg.task_id = "task-1"
        cfg.webhook_url = "https://example.com/webhook"
        cfg.auth_token = encode_auth({"token": "live-secret"})  # pragma: allowlist secret
        cfg.events = ["completed"]
        cfg.enabled = True

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [cfg]
        mock_db.query.return_value = mock_query

        rows = service.list_push_configs_for_dispatch(mock_db, agent_id="agent-1")
        assert len(rows) == 1
        assert rows[0]["auth_token"] == "live-secret"  # pragma: allowlist secret
        assert rows[0]["webhook_url"] == "https://example.com/webhook"

    def test_list_push_configs_for_dispatch_admin_bypass_skips_visibility_filter(self, service, mock_db):
        """Admin (user_email=None, token_teams=None) must not scope by ``_visible_agent_ids``.

        An admin listing for dispatch should see every row without paying
        the cost of a preliminary agent-id scan.
        """
        cfg = MagicMock()
        cfg.id = "cfg-1"
        cfg.a2a_agent_id = "agent-1"
        cfg.task_id = "task-1"
        cfg.webhook_url = "https://example.com/webhook"
        cfg.auth_token = None
        cfg.events = None
        cfg.enabled = True

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [cfg]
        mock_db.query.return_value = mock_query

        with patch.object(service, "_visible_agent_ids") as mock_visible:
            rows = service.list_push_configs_for_dispatch(mock_db, user_email=None, token_teams=None)
            mock_visible.assert_called_once_with(mock_db, None, None)

        assert len(rows) == 1

    def test_list_push_configs_for_dispatch_non_admin_scopes_via_sql(self, service, mock_db):
        """Non-admin caller must have visibility pushed into the SQL query."""
        cfg = MagicMock()
        cfg.id = "cfg-1"
        cfg.a2a_agent_id = "agent-visible"
        cfg.task_id = "task-1"
        cfg.webhook_url = "https://example.com/webhook"
        cfg.auth_token = None
        cfg.events = None
        cfg.enabled = True

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [cfg]
        mock_db.query.return_value = mock_query

        with patch.object(service, "_visible_agent_ids", return_value=["agent-visible"]):
            rows = service.list_push_configs_for_dispatch(mock_db, user_email="u@test.com", token_teams=["team-a"])

        # A non-admin call must apply a visibility filter — at minimum one
        # ``.filter()`` call beyond the optional agent_id/task_id filters.
        assert mock_query.filter.call_count >= 1
        assert len(rows) == 1

    def test_list_push_configs_for_dispatch_empty_visible_set_short_circuits(self, service, mock_db):
        """Empty visible-agents set must return [] without executing ``.all()``.

        A public-only user whose filters match no public agents should not
        cause a full scan of ``a2a_push_notification_configs``.
        """
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_db.query.return_value = mock_query

        with patch.object(service, "_visible_agent_ids", return_value=[]):
            rows = service.list_push_configs_for_dispatch(mock_db, user_email="u@test.com", token_teams=[])

        assert rows == []
        mock_query.all.assert_not_called()

    def test_list_push_configs_for_dispatch_drops_undecryptable_token(self, service, mock_db):
        """Ciphertext encrypted under a rotated key must not leak as a bearer token."""
        cfg = MagicMock()
        cfg.id = "cfg-1"
        cfg.a2a_agent_id = "agent-1"
        cfg.task_id = "task-1"
        cfg.webhook_url = "https://example.com/webhook"
        cfg.auth_token = "not-valid-ciphertext"
        cfg.events = None
        cfg.enabled = True

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [cfg]
        mock_db.query.return_value = mock_query

        rows = service.list_push_configs_for_dispatch(mock_db)
        assert rows[0]["auth_token"] is None


class TestFlushAndReplayEvents:
    """Unit tests for flush_events and replay_events."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def test_flush_events_inserts_and_returns_count(self, service, mock_db):
        """flush_events batch-inserts all events and returns the count."""
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        events = [
            {"task_id": "t1", "event_id": "e1", "sequence": 1, "event_type": "status_update", "payload": {"state": "running"}},
            {"task_id": "t1", "event_id": "e2", "sequence": 2, "event_type": "status_update", "payload": None},
        ]

        with patch("mcpgateway.db.A2ATaskEvent") as mock_model:
            mock_model.side_effect = [MagicMock(), MagicMock()]
            count = service.flush_events(mock_db, events)

        assert count == 2
        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called_once()

    def test_flush_events_empty_list(self, service, mock_db):
        """flush_events with an empty list commits and returns 0."""
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        count = service.flush_events(mock_db, [])

        assert count == 0
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()

    def test_replay_events_returns_ordered_list(self, service, mock_db):
        """replay_events returns events with sequence > after_sequence, ordered by sequence."""
        ev1 = MagicMock()
        ev2 = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [ev1, ev2]
        mock_db.query.return_value = mock_query

        row1 = {"id": "r1", "sequence": 5}
        row2 = {"id": "r2", "sequence": 6}
        with patch("mcpgateway.schemas.A2ATaskEventRead.model_validate") as mock_mv:
            mock_mv.side_effect = [
                MagicMock(model_dump=MagicMock(return_value=row1)),
                MagicMock(model_dump=MagicMock(return_value=row2)),
            ]
            result = service.replay_events(mock_db, "t1", after_sequence=4)

        assert result == [row1, row2]
        mock_query.filter.assert_called_once()
        mock_query.order_by.assert_called_once()
        mock_query.limit.assert_called_once()

    def test_replay_events_empty(self, service, mock_db):
        """replay_events returns an empty list when no events qualify."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        result = service.replay_events(mock_db, "t1", after_sequence=999)

        assert result == []


class TestPublishA2AInvalidation:
    """Unit tests for the module-level _publish_a2a_invalidation async function."""

    async def test_publishes_when_redis_available(self):
        """Message is published to Redis when a client is available."""
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()

        # get_redis_client is imported locally inside the function, so patch at its source.
        mock_get_redis = AsyncMock(return_value=mock_redis)
        with patch("mcpgateway.utils.redis_client.get_redis_client", mock_get_redis):
            # First-Party
            from mcpgateway.services.a2a_service import _publish_a2a_invalidation  # noqa: PLC0415

            await _publish_a2a_invalidation("agent_updated", agent_id="a1")

        mock_get_redis.assert_awaited_once()
        mock_redis.publish.assert_awaited_once()
        channel, payload_bytes = mock_redis.publish.call_args[0]
        assert channel == "mcpgw:a2a:invalidate"
        assert "agent_updated" in payload_bytes

    async def test_no_error_when_redis_unavailable(self):
        """No exception is raised when Redis client returns None."""
        mock_get_redis = AsyncMock(return_value=None)
        with patch("mcpgateway.utils.redis_client.get_redis_client", mock_get_redis):
            # First-Party
            from mcpgateway.services.a2a_service import _publish_a2a_invalidation  # noqa: PLC0415

            # Must not raise
            await _publish_a2a_invalidation("agent_deleted", agent_id="a99")

    async def test_no_error_on_redis_exception(self):
        """Exception from Redis publish is silently swallowed."""
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=ConnectionError("redis down"))

        mock_get_redis = AsyncMock(return_value=mock_redis)
        with patch("mcpgateway.utils.redis_client.get_redis_client", mock_get_redis):
            # First-Party
            from mcpgateway.services.a2a_service import _publish_a2a_invalidation  # noqa: PLC0415

            await _publish_a2a_invalidation("agent_created", agent_id="a2")


class TestShadowModeComparison:
    """Unit tests for the observe-only shadow mode block inside invoke_agent.

    Shadow mode no longer dispatches a second live call to the Rust sidecar
    (to avoid duplicate side effects on non-idempotent agents).  It only
    logs that the runtime is available.  The Rust runtime client should
    NOT be invoked.
    """

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def _make_agent(self):
        return SimpleNamespace(
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
            agent_type="generic",
            protocol_version="1.0",
        )

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_shadow_mode_does_not_invoke_rust(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Shadow mode logs readiness but does NOT dispatch to Rust sidecar."""
        agent = self._make_agent()
        response_body = {"result": "ok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(status_code=200, json=MagicMock(return_value=response_body))
        mock_get_client.return_value = mock_client

        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_enabled", True)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_delegate_enabled", False)

        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock()
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_rust_a2a_runtime_client", lambda: rust_runtime)

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()
        mock_db.commit = MagicMock()

        result = await service.invoke_agent(mock_db, "ag", {})

        assert result == response_body
        # Shadow mode must NOT invoke the Rust runtime (no dual-dispatch).
        rust_runtime.invoke.assert_not_awaited()

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_shadow_mode_not_triggered_when_delegate_enabled(self, mock_get_client, mock_fresh_db, mock_metrics_fn, service, mock_db, monkeypatch):
        """Shadow mode block is skipped when delegate_enabled=True (Rust handles the call)."""
        agent = self._make_agent()

        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock(return_value={"status_code": 200, "json": {"ok": True}, "text": ""})

        mock_db.execute.return_value.scalar_one_or_none.return_value = "a1"
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", lambda *a, **kw: agent)
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_rust_a2a_runtime_client", lambda: rust_runtime)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_enabled", True)
        monkeypatch.setattr(settings, "experimental_rust_a2a_runtime_delegate_enabled", True)

        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_fn.return_value = MagicMock()
        mock_db.commit = MagicMock()

        result = await service.invoke_agent(mock_db, "ag", {})

        # Only one invoke (delegated), not a second shadow invoke
        assert rust_runtime.invoke.await_count == 1
        assert result == {"ok": True}
        mock_get_client.assert_not_called()


# ---------------------------------------------------------------------------
# Visibility and task scoping tests
# ---------------------------------------------------------------------------


class TestCheckAgentAccessById:
    """Unit tests for _check_agent_access_by_id (fail-closed on missing agent)."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def test_deleted_agent_returns_false(self, service, mock_db):
        """Non-existent agent ID returns False (fail-closed)."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert service._check_agent_access_by_id(mock_db, "deleted-id", "user@test.com", ["team1"]) is False

    def test_public_agent_returns_true(self, service, mock_db):
        agent = MagicMock()
        agent.visibility = "public"
        mock_db.query.return_value.filter.return_value.first.return_value = agent
        assert service._check_agent_access_by_id(mock_db, "agent-1", "user@test.com", ["team1"]) is True

    def test_private_agent_wrong_owner_returns_false(self, service, mock_db):
        agent = MagicMock()
        agent.visibility = "private"
        agent.owner_email = "other@test.com"
        agent.team_id = "team1"
        mock_db.query.return_value.filter.return_value.first.return_value = agent
        assert service._check_agent_access_by_id(mock_db, "agent-1", "user@test.com", ["team1"]) is False

    def test_admin_bypass_returns_true(self, service, mock_db):
        agent = MagicMock()
        agent.visibility = "private"
        agent.owner_email = "other@test.com"
        mock_db.query.return_value.filter.return_value.first.return_value = agent
        assert service._check_agent_access_by_id(mock_db, "agent-1", None, None) is True


class TestVisibleAgentIds:
    """Unit tests for _visible_agent_ids visibility scoping SQL."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def test_admin_bypass_returns_none(self, service, mock_db):
        """Admin context (user_email=None, token_teams=None) returns None for unrestricted access."""
        result = service._visible_agent_ids(mock_db, user_email=None, token_teams=None)
        assert result is None

    def test_public_only_user_filters_to_public(self, service, mock_db):
        """Empty token_teams means public-only — query runs with public visibility filter."""
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [("id-pub",)]

        result = service._visible_agent_ids(mock_db, user_email="user@test.com", token_teams=[])
        assert result == ["id-pub"]
        # filter should have been called: once for enabled, once for visibility
        assert mock_query.filter.call_count >= 1

    def test_team_scoped_user(self, service, mock_db):
        """User with teams sees public + their team's agents + their private agents."""
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [("id-1",), ("id-2",)]

        result = service._visible_agent_ids(mock_db, user_email="user@test.com", token_teams=["team-a"])
        assert result == ["id-1", "id-2"]

    def test_no_user_email_returns_public_only(self, service, mock_db):
        """No user_email with some teams still acts as public-only."""
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        result = service._visible_agent_ids(mock_db, user_email=None, token_teams=["team1"])
        # Not admin (token_teams is not None), no user_email → is_public_only is True
        assert result == []

    def test_admin_with_email_returns_none(self, service, mock_db):
        """Admin with email context (token_teams=None, user_email set) still gets admin bypass only when both are None."""
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [("id-all",)]

        result = service._visible_agent_ids(mock_db, user_email="admin@test.com", token_teams=None)
        # token_teams=None but user_email set → NOT admin bypass, runs query
        assert result == ["id-all"]


class TestGetTask:
    """Unit tests for get_task visibility enforcement."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def _setup_task_query(self, mock_db, task, agent=None):
        """Wire mock_db.query() to return task on first call and agent on second.

        ``get_task``/``cancel_task`` now fetch with ``.limit(2).all()`` and
        refuse ambiguous matches; return a single-element list so the
        disambiguation guard passes through to the agent-visibility check.
        """
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [task] if task is not None else []

        mock_agent_query = MagicMock()
        mock_agent_query.filter.return_value = mock_agent_query
        mock_agent_query.first.return_value = agent

        mock_db.query.side_effect = [mock_query, mock_agent_query]

    def test_task_not_found_returns_none(self, service, mock_db):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        assert service.get_task(mock_db, "missing") is None

    def test_ambiguous_task_without_agent_id_returns_none(self, service, mock_db):
        """Two matches without agent_id must refuse to guess."""
        task_a = MagicMock()
        task_a.a2a_agent_id = "agent-a"
        task_b = MagicMock()
        task_b.a2a_agent_id = "agent-b"

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [task_a, task_b]
        mock_db.query.return_value = mock_query

        assert service.get_task(mock_db, "shared-task-id", user_email=None, token_teams=None) is None

    def _wire_task(self, **overrides):
        """Return a MagicMock with the attributes _task_to_wire needs."""
        t = MagicMock()
        t.task_id = overrides.get("task_id", "t1")
        t.a2a_agent_id = overrides.get("a2a_agent_id", "agent-1")
        t.state = overrides.get("state", "completed")
        t.context_id = overrides.get("context_id", None)
        t.latest_message = overrides.get("latest_message", None)
        t.last_error = overrides.get("last_error", None)
        t.payload = overrides.get("payload", None)
        return t

    def test_task_visible_to_admin(self, service, mock_db):
        """Admin bypass (user_email=None, token_teams=None) sees any task."""
        task = self._wire_task()
        agent = MagicMock()
        agent.visibility = "private"
        agent.owner_email = "other@test.com"
        self._setup_task_query(mock_db, task, agent)

        result = service.get_task(mock_db, "t1", user_email=None, token_teams=None)

        assert result["id"] == "t1"

    def test_task_hidden_from_wrong_team(self, service, mock_db):
        """Team-scoped user cannot see tasks owned by agents in a different team."""
        task = MagicMock()
        task.a2a_agent_id = "agent-1"
        agent = MagicMock()
        agent.visibility = "team"
        agent.team_id = "team-b"
        agent.owner_email = "other@test.com"
        self._setup_task_query(mock_db, task, agent)

        result = service.get_task(mock_db, "t1", user_email="user@test.com", token_teams=["team-a"])

        assert result is None

    def test_task_visible_to_correct_team(self, service, mock_db):
        """Team-scoped user can see tasks owned by agents in their team."""
        task = self._wire_task()
        agent = MagicMock()
        agent.visibility = "team"
        agent.team_id = "team-a"
        agent.owner_email = "other@test.com"
        self._setup_task_query(mock_db, task, agent)

        result = service.get_task(mock_db, "t1", user_email="user@test.com", token_teams=["team-a"])
        assert result["id"] == "t1"

    def test_task_visible_when_agent_deleted(self, service, mock_db):
        """If the owning agent was deleted, the task is still returned (agent=None passes the check)."""
        task = self._wire_task(a2a_agent_id="deleted-agent")
        self._setup_task_query(mock_db, task, agent=None)

        result = service.get_task(mock_db, "t1", user_email="user@test.com", token_teams=["team-a"])
        assert result["id"] == "t1"

    def test_public_only_user_sees_public_agent_task(self, service, mock_db):
        """Public-only user (empty teams) can see tasks for public agents."""
        task = self._wire_task()
        agent = MagicMock()
        agent.visibility = "public"
        self._setup_task_query(mock_db, task, agent)

        result = service.get_task(mock_db, "t1", user_email="user@test.com", token_teams=[])
        assert result["id"] == "t1"

    def test_public_only_user_cannot_see_private_agent_task(self, service, mock_db):
        """Public-only user (empty teams) cannot see tasks for private agents."""
        task = MagicMock()
        task.a2a_agent_id = "agent-1"
        agent = MagicMock()
        agent.visibility = "private"
        agent.owner_email = "user@test.com"
        self._setup_task_query(mock_db, task, agent)

        result = service.get_task(mock_db, "t1", user_email="user@test.com", token_teams=[])

        assert result is None


class TestListTasks:
    """Unit tests for list_tasks visibility scoping."""

    @pytest.fixture
    def service(self):
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def test_admin_sees_all_tasks(self, service, mock_db):
        """Admin bypass does not filter by agent IDs."""
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = []

        with patch.object(service, "_visible_agent_ids", return_value=None):
            result = service.list_tasks(mock_db, user_email=None, token_teams=None)

        assert result == []
        # Verify .in_() was NOT called (no agent ID filter applied)
        for call in mock_query.filter.call_args_list:
            for arg in call.args:
                assert "in_" not in str(arg), "Admin should not have .in_() filter"

    def test_team_scoped_user_gets_filtered_tasks(self, service, mock_db):
        """Team user only sees tasks for visible agents."""
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        task = MagicMock()
        task.task_id = "t1"
        task.state = "completed"
        task.context_id = None
        task.latest_message = None
        task.last_error = None
        task.payload = None
        mock_query.all.return_value = [task]

        with patch.object(service, "_visible_agent_ids", return_value=["agent-1"]):
            result = service.list_tasks(mock_db, user_email="user@test.com", token_teams=["team-a"])

        assert result == [{"id": "t1", "contextId": None, "status": {"state": "completed"}}]

    def test_state_filter_applied(self, service, mock_db):
        """State parameter adds a filter clause."""
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = []

        with patch.object(service, "_visible_agent_ids", return_value=None):
            service.list_tasks(mock_db, state="completed", user_email=None, token_teams=None)

        # filter called at least once for state
        assert mock_query.filter.call_count >= 1
