# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_passthrough_headers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for A2A agent passthrough_headers functionality (Issue #5004).

This test suite validates that passthrough_headers are correctly forwarded
in A2A agent invocations via the direct REST path (/a2a/{name}/invoke).
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.a2a_service.structured_logger") as mock_logger:
        mock_logger.log = MagicMock(return_value=None)
        mock_logger.info = MagicMock(return_value=None)
        yield mock_logger


@pytest.fixture(autouse=True)
def bypass_uaid_security_for_tests(monkeypatch):
    """Bypass UAID security validation for these tests."""
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allow_all_domains", True)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_max_federation_hops", 5)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.mcpgateway_a2a_default_timeout", 30)


class TestA2APassthroughHeaders:
    """Test suite for A2A agent passthrough_headers functionality (Issue #5004)."""

    @pytest.fixture
    def service(self):
        """Create A2A agent service instance."""
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def sample_agent_with_passthrough(self):
        """Sample agent with passthrough_headers configured."""
        agent_id = str(uuid.uuid4())
        agent = MagicMock(spec=DbA2AAgent)
        agent.id = agent_id
        agent.name = "test-passthrough-agent"
        agent.enabled = True
        agent.endpoint_url = "http://localhost:9999/agent"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        agent.protocol_version = "v1.0"
        agent.agent_type = "jsonrpc"
        agent.visibility = "public"
        agent.team_id = None
        agent.owner_email = None
        agent.passthrough_headers = ["x-user-id", "x-tenant-id"]
        return agent

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    async def test_passthrough_headers_forwarded_when_whitelisted(
        self, mock_metrics_buffer_fn, mock_fresh_db, mock_get_client, mock_get_for_update, service, mock_db, sample_agent_with_passthrough
    ):
        """Test that whitelisted passthrough headers are forwarded to downstream agent."""
        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"messageId": "msg-1", "role": "ROLE_AGENT", "parts": [{"text": "Response"}]},
        }
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_agent_with_passthrough.id
        mock_get_for_update.return_value = sample_agent_with_passthrough
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        # Mock fresh_db_session for last_interaction update
        mock_ts_db = MagicMock()
        mock_ts_db.commit = MagicMock()
        mock_ts_db.close = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db

        # Request headers including whitelisted and non-whitelisted headers
        request_headers = {
            "x-user-id": "alice@example.com",
            "x-tenant-id": "tenant-123",
            "authorization": "Bearer secret-token",  # Should be filtered out (not in whitelist)
            "x-secret": "should-not-forward",  # Should be filtered out (not in whitelist)
        }

        # Invoke agent with request_headers
        result = await service.invoke_agent(
            db=mock_db,
            agent_name="test-passthrough-agent",
            parameters={"message": {"text": "Hello"}},
            interaction_type="query",
            user_id="user-123",
            user_email="alice@example.com",
            token_teams=[],
            request_headers=request_headers,
        )

        # Verify result
        assert result is not None
        assert "result" in result

        # Verify HTTP client was called
        assert mock_client.post.called
        call_args = mock_client.post.call_args

        # Extract headers from the call
        headers = call_args.kwargs.get("headers", {})

        # Verify whitelisted headers were forwarded
        assert "x-user-id" in headers
        assert headers["x-user-id"] == "alice@example.com"
        assert "x-tenant-id" in headers
        assert headers["x-tenant-id"] == "tenant-123"

        # Verify non-whitelisted headers were NOT forwarded
        assert "authorization" not in headers or headers["authorization"] != "Bearer secret-token"
        assert "x-secret" not in headers

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    async def test_passthrough_headers_case_insensitive_matching(
        self, mock_metrics_buffer_fn, mock_fresh_db, mock_get_client, mock_get_for_update, service, mock_db, sample_agent_with_passthrough
    ):
        """Test that passthrough header matching is case-insensitive."""
        # Mock metrics buffer
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_agent_with_passthrough.id
        mock_get_for_update.return_value = sample_agent_with_passthrough
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        # Mock fresh_db_session
        mock_ts_db = MagicMock()
        mock_ts_db.commit = MagicMock()
        mock_ts_db.close = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db

        # Request headers with different case (X-User-ID vs x-user-id in whitelist)
        request_headers = {
            "X-User-ID": "bob@example.com",  # Capital letters
            "X-TENANT-ID": "tenant-456",  # All caps
        }

        # Invoke agent
        result = await service.invoke_agent(
            db=mock_db,
            agent_name="test-passthrough-agent",
            parameters={"message": {"text": "Hello"}},
            interaction_type="query",
            user_id="user-123",
            user_email="bob@example.com",
            token_teams=[],
            request_headers=request_headers,
        )

        # Verify result
        assert result is not None

        # Verify HTTP client was called and headers were forwarded despite case difference
        assert mock_client.post.called
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})

        # Headers should be normalized to lowercase to prevent duplicate headers
        assert "x-user-id" in headers, f"Header not normalized to lowercase: {list(headers.keys())}"
        assert headers["x-user-id"] == "bob@example.com"
        assert "x-tenant-id" in headers, f"Header not normalized to lowercase: {list(headers.keys())}"
        assert headers["x-tenant-id"] == "tenant-456"

        # Verify no uppercase versions exist (would indicate duplication bug)
        assert "X-User-ID" not in headers, "Header key should be normalized to lowercase"
        assert "X-TENANT-ID" not in headers, "Header key should be normalized to lowercase"

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    async def test_no_headers_forwarded_when_passthrough_not_configured(
        self, mock_metrics_buffer_fn, mock_fresh_db, mock_get_client, mock_get_for_update, service, mock_db
    ):
        """Test that NO headers are forwarded when passthrough_headers is not configured (fail-closed)."""
        # Create agent WITHOUT passthrough_headers
        agent_id = str(uuid.uuid4())
        agent = MagicMock(spec=DbA2AAgent)
        agent.id = agent_id
        agent.name = "test-no-passthrough-agent"
        agent.enabled = True
        agent.endpoint_url = "http://localhost:9999/agent"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        agent.protocol_version = "v1.0"
        agent.agent_type = "jsonrpc"
        agent.visibility = "public"
        agent.team_id = None
        agent.owner_email = None
        agent.passthrough_headers = None  # No passthrough configured

        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent.id
        mock_get_for_update.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        # Mock fresh_db_session
        mock_ts_db = MagicMock()
        mock_ts_db.commit = MagicMock()
        mock_ts_db.close = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db

        # Request headers
        request_headers = {
            "x-user-id": "alice@example.com",
            "x-tenant-id": "tenant-123",
        }

        # Invoke agent
        result = await service.invoke_agent(
            db=mock_db,
            agent_name="test-no-passthrough-agent",
            parameters={"message": {"text": "Hello"}},
            interaction_type="query",
            user_id="user-123",
            user_email="alice@example.com",
            token_teams=[],
            request_headers=request_headers,
        )

        # Verify result
        assert result is not None

        # Verify HTTP client was called
        assert mock_client.post.called
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})

        # Verify NO request headers were forwarded (fail-closed security default)
        assert "x-user-id" not in headers
        assert "x-tenant-id" not in headers

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    async def test_empty_passthrough_headers_blocks_all(
        self, mock_metrics_buffer_fn, mock_fresh_db, mock_get_client, mock_get_for_update, service, mock_db
    ):
        """Test that empty passthrough_headers list blocks all headers (fail-closed)."""
        # Create agent with EMPTY passthrough_headers list
        agent_id = str(uuid.uuid4())
        agent = MagicMock(spec=DbA2AAgent)
        agent.id = agent_id
        agent.name = "test-empty-passthrough-agent"
        agent.enabled = True
        agent.endpoint_url = "http://localhost:9999/agent"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        agent.protocol_version = "v1.0"
        agent.agent_type = "jsonrpc"
        agent.visibility = "public"
        agent.team_id = None
        agent.owner_email = None
        agent.passthrough_headers = []  # Empty list = block all

        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent.id
        mock_get_for_update.return_value = agent
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        # Mock fresh_db_session
        mock_ts_db = MagicMock()
        mock_ts_db.commit = MagicMock()
        mock_ts_db.close = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db

        # Request headers
        request_headers = {
            "x-user-id": "alice@example.com",
            "x-tenant-id": "tenant-123",
        }

        # Invoke agent
        result = await service.invoke_agent(
            db=mock_db,
            agent_name="test-empty-passthrough-agent",
            parameters={"message": {"text": "Hello"}},
            interaction_type="query",
            user_id="user-123",
            user_email="alice@example.com",
            token_teams=[],
            request_headers=request_headers,
        )

        # Verify result
        assert result is not None

        # Verify HTTP client was called
        assert mock_client.post.called
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})

        # Verify NO headers were forwarded (empty whitelist = block all)
        assert "x-user-id" not in headers
        assert "x-tenant-id" not in headers
