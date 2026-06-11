# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_passthrough_headers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for passthrough header forwarding in A2A agent invocations.

Verifies that A2A agent invocations correctly forward whitelisted headers
from the original request to downstream agents. See GitHub issue #3621.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_service import A2AService


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.commit = MagicMock()
    db.close = MagicMock()
    return db


@pytest.fixture
def mock_a2a_agent():
    """Mock A2A agent with passthrough_headers configuration."""
    agent = MagicMock()
    agent.id = "agent-123"
    agent.name = "test-agent"
    agent.team_id = "team-1"
    agent.visibility = "team"
    agent.enabled = True
    agent.agent_type = "generic"
    agent.endpoint_url = "https://downstream.example.com/agent"
    agent.protocol_version = "1.0"
    agent.auth_type = None
    agent.auth_value = None
    agent.auth_query_params = None
    agent.tags = []
    agent.oauth_config = None
    agent.passthrough_headers = ["Authorization", "X-Tenant-ID"]
    agent.uaid = None
    agent.uaid_native_id = None
    return agent


@pytest.fixture
def a2a_service():
    """A2A service instance."""
    service = A2AService()
    return service


# ---------------------------------------------------------------------------
# Tests for passthrough header forwarding (happy path)
# ---------------------------------------------------------------------------
class TestA2APassthroughHeadersHappyPath:
    """Test that A2A agents correctly forward whitelisted headers."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_forwards_whitelisted_headers_to_downstream_agent(
        self, mock_correlation_id, mock_httpx_client, mock_db, mock_a2a_agent, a2a_service
    ):
        """Happy path: whitelisted headers are forwarded to downstream agent HTTP call."""
        mock_correlation_id.return_value = "test-correlation-123"

        # Mock DB query to return our test agent
        mock_db.query.return_value.filter.return_value.first.return_value = mock_a2a_agent

        # Mock HTTP response from downstream agent
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        # Call invoke_agent with passthrough headers
        request_headers = {
            "authorization": "Bearer client-secret-token",
            "x-tenant-id": "acme-corp",
            "x-unrelated-header": "should-not-forward",
        }

        result = await a2a_service.invoke_agent(
            agent_name="test-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="user@example.com",
            token_teams=["team-1"],
            request_headers=request_headers,
        )

        # Verify the downstream HTTP call was made
        mock_client_instance.post.assert_called_once()
        call_kwargs = mock_client_instance.post.call_args.kwargs

        # Verify whitelisted headers were forwarded
        sent_headers = call_kwargs.get("headers", {})
        assert "authorization" in sent_headers
        assert sent_headers["authorization"] == "Bearer client-secret-token"
        assert "x-tenant-id" in sent_headers
        assert sent_headers["x-tenant-id"] == "acme-corp"

        # Verify non-whitelisted header was NOT forwarded
        assert "x-unrelated-header" not in sent_headers

        assert result is not None

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_case_insensitive_header_matching(self, mock_correlation_id, mock_httpx_client, mock_db, mock_a2a_agent, a2a_service):
        """Headers are matched case-insensitively against whitelist."""
        mock_correlation_id.return_value = "test-correlation-123"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_a2a_agent

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        # Request headers have different casing than whitelist
        request_headers = {
            "AUTHORIZATION": "Bearer token",
            "X-TENANT-ID": "acme",
        }

        await a2a_service.invoke_agent(
            agent_name="test-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="user@example.com",
            token_teams=["team-1"],
            request_headers=request_headers,
        )

        call_kwargs = mock_client_instance.post.call_args.kwargs
        sent_headers = call_kwargs.get("headers", {})

        # Headers should be normalized to lowercase
        assert "authorization" in sent_headers or "AUTHORIZATION" in sent_headers
        assert "x-tenant-id" in sent_headers or "X-TENANT-ID" in sent_headers


# ---------------------------------------------------------------------------
# Tests for security deny-paths
# ---------------------------------------------------------------------------
class TestA2APassthroughHeadersSecurityDenyPaths:
    """Test security boundaries and deny-paths for passthrough headers."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_denies_headers_not_in_whitelist(self, mock_correlation_id, mock_httpx_client, mock_db, mock_a2a_agent, a2a_service):
        """Deny-path: headers not in whitelist are blocked even if present in request."""
        mock_correlation_id.return_value = "test-correlation-123"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_a2a_agent

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        request_headers = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
            "x-attacker-header": "malicious-value",
            "x-internal-secret": "should-never-forward",
        }

        await a2a_service.invoke_agent(
            agent_name="test-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="user@example.com",
            token_teams=["team-1"],
            request_headers=request_headers,
        )

        call_kwargs = mock_client_instance.post.call_args.kwargs
        sent_headers = call_kwargs.get("headers", {})

        # Only whitelisted headers should be present
        assert "authorization" in sent_headers
        assert "x-tenant-id" in sent_headers
        assert "x-attacker-header" not in sent_headers
        assert "x-internal-secret" not in sent_headers

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_no_headers_forwarded_when_whitelist_is_empty(self, mock_correlation_id, mock_httpx_client, mock_db, a2a_service):
        """Deny-path: when passthrough_headers is empty, no headers are forwarded."""
        mock_correlation_id.return_value = "test-correlation-123"

        agent_no_whitelist = MagicMock()
        agent_no_whitelist.id = "agent-456"
        agent_no_whitelist.name = "no-passthrough-agent"
        agent_no_whitelist.team_id = "team-1"
        agent_no_whitelist.visibility = "team"
        agent_no_whitelist.enabled = True
        agent_no_whitelist.agent_type = "http"
        agent_no_whitelist.endpoint_url = "https://downstream.example.com/agent"
        agent_no_whitelist.protocol_version = "1.0"
        agent_no_whitelist.auth_type = None
        agent_no_whitelist.auth_value = None
        agent_no_whitelist.auth_query_params = None
        agent_no_whitelist.tags = []
        agent_no_whitelist.oauth_config = None
        agent_no_whitelist.passthrough_headers = []  # Empty whitelist
        agent_no_whitelist.uaid = None
        agent_no_whitelist.uaid_native_id = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = agent_no_whitelist
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        request_headers = {
            "authorization": "Bearer secret",
            "x-tenant-id": "acme",
        }

        await a2a_service.invoke_agent(
            agent_name="no-passthrough-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="user@example.com",
            token_teams=["team-1"],
            request_headers=request_headers,
        )

        call_kwargs = mock_client_instance.post.call_args.kwargs
        sent_headers = call_kwargs.get("headers", {})

        # No passthrough headers should be forwarded
        # Only default headers like Content-Type, X-Correlation-ID may be present
        assert "authorization" not in sent_headers
        assert "x-tenant-id" not in sent_headers

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_no_headers_forwarded_when_whitelist_is_none(self, mock_correlation_id, mock_httpx_client, mock_db, a2a_service):
        """Deny-path: when passthrough_headers is None, no headers are forwarded."""
        mock_correlation_id.return_value = "test-correlation-123"

        agent_none_whitelist = MagicMock()
        agent_none_whitelist.id = "agent-789"
        agent_none_whitelist.name = "none-passthrough-agent"
        agent_none_whitelist.team_id = "team-1"
        agent_none_whitelist.visibility = "team"
        agent_none_whitelist.enabled = True
        agent_none_whitelist.agent_type = "http"
        agent_none_whitelist.endpoint_url = "https://downstream.example.com/agent"
        agent_none_whitelist.protocol_version = "1.0"
        agent_none_whitelist.auth_type = None
        agent_none_whitelist.auth_value = None
        agent_none_whitelist.auth_query_params = None
        agent_none_whitelist.tags = []
        agent_none_whitelist.oauth_config = None
        agent_none_whitelist.passthrough_headers = None  # None whitelist
        agent_none_whitelist.uaid = None
        agent_none_whitelist.uaid_native_id = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = agent_none_whitelist
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        request_headers = {
            "authorization": "Bearer secret",
            "x-tenant-id": "acme",
        }

        await a2a_service.invoke_agent(
            agent_name="none-passthrough-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="user@example.com",
            token_teams=["team-1"],
            request_headers=request_headers,
        )

        call_kwargs = mock_client_instance.post.call_args.kwargs
        sent_headers = call_kwargs.get("headers", {})

        # No passthrough headers should be forwarded
        assert "authorization" not in sent_headers
        assert "x-tenant-id" not in sent_headers


# ---------------------------------------------------------------------------
# Tests for backward compatibility
# ---------------------------------------------------------------------------
class TestA2APassthroughHeadersBackwardCompatibility:
    """Test backward compatibility when request_headers is not provided."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_works_when_request_headers_is_none(self, mock_correlation_id, mock_httpx_client, mock_db, mock_a2a_agent, a2a_service):
        """Backward compatibility: works when request_headers is None."""
        mock_correlation_id.return_value = "test-correlation-123"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_a2a_agent

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        result = await a2a_service.invoke_agent(
            agent_name="test-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="user@example.com",
            token_teams=["team-1"],
            request_headers=None,  # No headers provided
        )

        # Should complete without error
        assert result is not None
        mock_client_instance.post.assert_called_once()

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_works_when_request_headers_is_empty_dict(self, mock_correlation_id, mock_httpx_client, mock_db, mock_a2a_agent, a2a_service):
        """Backward compatibility: works when request_headers is empty dict."""
        mock_correlation_id.return_value = "test-correlation-123"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_a2a_agent

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        result = await a2a_service.invoke_agent(
            agent_name="test-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="user@example.com",
            token_teams=["team-1"],
            request_headers={},  # Empty dict
        )

        # Should complete without error
        assert result is not None
        mock_client_instance.post.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for audit logging
# ---------------------------------------------------------------------------
class TestA2APassthroughHeadersAuditLogging:
    """Test that passthrough header forwarding is logged for security audit."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.logger")
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    async def test_audit_log_records_forwarded_headers(self, mock_correlation_id, mock_httpx_client, mock_logger, mock_db, mock_a2a_agent, a2a_service):
        """Security audit: forwarded headers are logged."""
        mock_correlation_id.return_value = "test-correlation-123"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_a2a_agent

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_httpx_client.return_value = mock_client_instance

        request_headers = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
        }

        await a2a_service.invoke_agent(
            agent_name="test-agent",
            parameters={"query": "test"},
            interaction_type="invoke",
            db=mock_db,
            user_email="auditor@example.com",
            token_teams=["team-1"],
            request_headers=request_headers,
        )

        # Verify audit log was written
        # Look for logger.info call that mentions "passthrough headers forwarded"
        info_calls = [call for call in mock_logger.info.call_args_list]
        audit_log_found = any(
            "passthrough headers" in str(call).lower() or "forwarded" in str(call).lower() for call in info_calls
        )
        assert audit_log_found, "Expected audit log for passthrough headers forwarding"
