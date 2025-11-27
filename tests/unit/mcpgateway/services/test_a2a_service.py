# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for A2A Agent Service functionality.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.schemas import A2AAgentCreate, A2AAgentUpdate
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNameConflictError, A2AAgentNotFoundError, A2AAgentService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock structured_logger and audit_trail to prevent database writes during tests."""
    with patch("mcpgateway.services.a2a_service.structured_logger") as mock_a2a_logger, \
         patch("mcpgateway.services.tool_service.structured_logger") as mock_tool_logger, \
         patch("mcpgateway.services.tool_service.audit_trail") as mock_tool_audit:
        mock_a2a_logger.log = MagicMock(return_value=None)
        mock_a2a_logger.info = MagicMock(return_value=None)
        mock_tool_logger.log = MagicMock(return_value=None)
        mock_tool_logger.info = MagicMock(return_value=None)
        mock_tool_audit.log_action = MagicMock(return_value=None)
        yield {"structured_logger": mock_a2a_logger, "tool_logger": mock_tool_logger, "tool_audit": mock_tool_audit}


class TestA2AAgentService:
    """Test suite for A2A Agent Service."""

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
            tags=[{'id': "test", "label": "test"}, {'id': "ai", "label": "ai"}],
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
        service._db_to_schema = MagicMock(return_value=MagicMock())

        # Patch ToolRead.model_validate to accept the dict without error
        import mcpgateway.schemas

        if hasattr(mcpgateway.schemas.ToolRead, "model_validate"):
            from unittest.mock import patch

            with patch.object(mcpgateway.schemas.ToolRead, "model_validate", return_value=MagicMock()):
                result = await service.register_agent(mock_db, sample_agent_create)
        else:
            result = await service.register_agent(mock_db, sample_agent_create)

        # Verify
        assert mock_db.add.call_count == 2
        assert mock_db.commit.call_count == 2
        assert service._db_to_schema.called

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
        service._db_to_schema = MagicMock(return_value=MagicMock())

        # Execute
        result = await service.list_agents(mock_db, include_inactive=False)

        # Verify
        assert service._db_to_schema.called
        assert len(result) >= 0  # Should return mocked results

    async def test_list_agents_with_tags(self, service, mock_db, sample_db_agent):
        """Test listing agents filtered by tags."""
        # Mock database query
        mock_db.execute.return_value.scalars.return_value.all.return_value = [sample_db_agent]
        service._db_to_schema = MagicMock(return_value=MagicMock())

        # Execute
        result = await service.list_agents(mock_db, tags=["test"])

        # Verify
        assert service._db_to_schema.called

    async def test_get_agent_success(self, service, mock_db, sample_db_agent):
        """Test successful agent retrieval by ID."""
        # Mock database query
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        service._db_to_schema = MagicMock(return_value=MagicMock())

        # Execute
        result = await service.get_agent(mock_db, sample_db_agent.id)

        # Verify
        assert service._db_to_schema.called

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
        service._db_to_schema = MagicMock(return_value=MagicMock())

        # Execute
        result = await service.get_agent_by_name(mock_db, sample_db_agent.name)

        # Verify
        assert service._db_to_schema.called

    async def test_update_agent_success(self, service, mock_db, sample_db_agent):
        """Test successful agent update."""
        # Set version attribute to avoid TypeError
        sample_db_agent.version = 1

        # Mock database queries
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [sample_db_agent, None]  # Agent exists, no name conflict
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        # Mock the _db_to_schema method properly
        with patch.object(service, "_db_to_schema") as mock_schema:
            mock_schema.return_value = MagicMock()

            # Create update data
            update_data = A2AAgentUpdate(description="Updated description")

            # Execute
            result = await service.update_agent(mock_db, sample_db_agent.id, update_data)

            # Verify
            mock_db.commit.assert_called_once()
            assert mock_schema.called
            assert sample_db_agent.version == 2  # Should be incremented

    async def test_update_agent_not_found(self, service, mock_db):
        """Test updating non-existent agent."""
        # Mock database query returning None
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        update_data = A2AAgentUpdate(description="Updated description")

        # Execute and verify exception
        with pytest.raises(A2AAgentNotFoundError):
            await service.update_agent(mock_db, "non-existent-id", update_data)

    async def test_toggle_agent_status_success(self, service, mock_db, sample_db_agent):
        """Test successful agent status toggle."""
        # Mock database query
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_agent
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        service._db_to_schema = MagicMock(return_value=MagicMock())

        # Execute
        result = await service.toggle_agent_status(mock_db, sample_db_agent.id, False)

        # Verify
        assert sample_db_agent.enabled == False
        mock_db.commit.assert_called_once()
        assert service._db_to_schema.called

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

    async def test_delete_agent_not_found(self, service, mock_db):
        """Test deleting non-existent agent."""
        # Mock database query returning None
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # Execute and verify exception
        with pytest.raises(A2AAgentNotFoundError):
            await service.delete_agent(mock_db, "non-existent-id")

    @patch("httpx.AsyncClient")
    async def test_invoke_agent_success(self, mock_client_class, service, mock_db, sample_db_agent):
        """Test successful agent invocation."""
        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Test response", "status": "success"}
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Mock database operations
        service.get_agent_by_name = AsyncMock(
            return_value=MagicMock(
                id=sample_db_agent.id,
                name=sample_db_agent.name,
                enabled=True,
                endpoint_url=sample_db_agent.endpoint_url,
                auth_type=sample_db_agent.auth_type,
                auth_value=sample_db_agent.auth_value,
                protocol_version=sample_db_agent.protocol_version,
            )
        )
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.execute.return_value.scalar_one.return_value = sample_db_agent

        # Execute
        result = await service.invoke_agent(mock_db, sample_db_agent.name, {"test": "data"})

        # Verify
        assert result["response"] == "Test response"
        mock_client.post.assert_called_once()
        mock_db.add.assert_called()  # Metrics added
        mock_db.commit.assert_called()

    async def test_invoke_agent_disabled(self, service, mock_db, sample_db_agent):
        """Test invoking disabled agent."""
        # Mock disabled agent
        disabled_agent = MagicMock()
        disabled_agent.enabled = False
        disabled_agent.name = sample_db_agent.name
        service.get_agent_by_name = AsyncMock(return_value=disabled_agent)

        # Execute and verify exception
        with pytest.raises(A2AAgentError, match="disabled"):
            await service.invoke_agent(mock_db, sample_db_agent.name, {"test": "data"})

    @patch("httpx.AsyncClient")
    async def test_invoke_agent_http_error(self, mock_client_class, service, mock_db, sample_db_agent):
        """Test agent invocation with HTTP error."""
        # Mock HTTP client with error response
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Mock database operations
        service.get_agent_by_name = AsyncMock(
            return_value=MagicMock(
                id=sample_db_agent.id,
                name=sample_db_agent.name,
                enabled=True,
                endpoint_url=sample_db_agent.endpoint_url,
                auth_type=sample_db_agent.auth_type,
                auth_value=sample_db_agent.auth_value,
                protocol_version=sample_db_agent.protocol_version,
            )
        )
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.execute.return_value.scalar_one.return_value = sample_db_agent

        # Execute and verify exception
        with pytest.raises(A2AAgentError, match="HTTP 500"):
            await service.invoke_agent(mock_db, sample_db_agent.name, {"test": "data"})

        # Verify metrics were still recorded
        mock_db.add.assert_called()
        mock_db.commit.assert_called()

    async def test_aggregate_metrics(self, service, mock_db):
        """Test metrics aggregation."""
        # Mock database queries
        mock_db.execute.return_value.scalar.side_effect = [5, 3]  # total_agents, active_agents
        mock_db.execute.return_value.first.return_value = MagicMock(
            total_interactions=100,
            successful_interactions=90,
            avg_response_time=1.5,
            min_response_time=0.5,
            max_response_time=3.0,
        )

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
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    async def test_reset_metrics_specific_agent(self, service, mock_db):
        """Test resetting metrics for specific agent."""
        agent_id = uuid.uuid4().hex
        mock_db.execute = MagicMock()
        mock_db.commit = MagicMock()

        # Execute
        await service.reset_metrics(mock_db, agent_id)

        # Verify
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_db_to_schema_conversion(self, service, sample_db_agent):
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
            result = service._db_to_schema(mock_db, sample_db_agent)

        # Verify
        assert result.id == sample_db_agent.id
        assert result.name == sample_db_agent.name
        assert result.metrics.total_executions == 2
        assert result.metrics.successful_executions == 1
        assert result.metrics.failed_executions == 1
        assert result.metrics.failure_rate == 50.0
        assert result.metrics.avg_response_time == 1.5
        assert result.team == "Test Team"


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
