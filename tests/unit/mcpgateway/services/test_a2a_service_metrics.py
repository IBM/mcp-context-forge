# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service_metrics.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for A2AAgentService metrics functionality in convert_agent_to_read.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import A2AAgentMetric
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def a2a_service():
    """Create A2AAgentService instance."""
    return A2AAgentService()


def create_test_agent():
    """Create a real A2AAgent with all required fields for testing.

    Returns a DbA2AAgent instance with all required fields populated.
    """
    agent = DbA2AAgent()
    agent.id = "test-agent-id"
    agent.name = "Test Agent"
    agent.slug = "test-agent"
    agent.description = "Test agent description"
    agent.base_url = "http://test-agent.example.com"
    agent.endpoint_url = "http://test-agent.example.com/agent"
    agent.protocol = "jsonrpc"
    agent.agent_type = "assistant"
    agent.protocol_version = "1.0"
    agent.capabilities = {"streaming": True}
    agent.config = {}
    agent.enabled = True
    agent.is_enabled = True
    agent.reachable = True
    agent.owner_email = "test@example.com"
    agent.team_id = "test-team"
    agent.visibility = "public"
    agent.tags = [{"key": "env", "value": "test"}]
    agent.last_interaction = None
    agent.passthrough_headers = None
    agent.auth_type = None
    agent.auth_value = None
    agent.oauth_config = None
    agent.auth_query_params = None
    agent.created_at = datetime.now(timezone.utc)
    agent.updated_at = datetime.now(timezone.utc)
    # Set team attribute to avoid DB query
    agent.team = None
    return agent


def test_convert_agent_to_read_with_metrics_uses_property(mock_db, a2a_service):
    """Test convert_agent_to_read uses metrics_summary property when include_metrics=True."""
    # Create agent with pre-loaded metrics
    agent = create_test_agent()
    now = datetime.now(timezone.utc)

    # Create diverse metrics to test aggregation
    agent.metrics = [
        A2AAgentMetric(response_time=0.5, is_success=True, timestamp=now),
        A2AAgentMetric(response_time=2.5, is_success=False, timestamp=now),
        A2AAgentMetric(response_time=1.2, is_success=True, timestamp=now),
    ]

    # Call convert_agent_to_read with include_metrics=True
    # Pass team_map={} to avoid DB query for team name
    result = a2a_service.convert_agent_to_read(agent, include_metrics=True, db=mock_db, team_map={})

    # Verify the returned metrics are computed from loaded metrics
    assert result.metrics is not None
    assert result.metrics.total_executions == 3
    assert result.metrics.successful_executions == 2
    assert result.metrics.failed_executions == 1
    # failure_rate should be 1/3 ≈ 0.333...
    assert abs(result.metrics.failure_rate - (1 / 3)) < 0.001
    assert result.metrics.min_response_time == 0.5
    assert result.metrics.max_response_time == 2.5
    # avg should be (0.5 + 2.5 + 1.2) / 3 ≈ 1.4
    assert abs(result.metrics.avg_response_time - 1.4) < 0.001
    assert result.metrics.last_execution_time == now


def test_convert_agent_to_read_without_metrics_returns_none(mock_db, a2a_service):
    """Test convert_agent_to_read returns None for metrics when include_metrics=False."""
    agent = create_test_agent()

    # Call convert_agent_to_read with include_metrics=False (default)
    # Pass team_map={} to avoid DB query for team name
    result = a2a_service.convert_agent_to_read(agent, include_metrics=False, db=mock_db, team_map={})

    # Verify metrics is None
    assert result.metrics is None


def test_convert_agent_to_read_metrics_fraction_not_percentage(mock_db, a2a_service):
    """Test convert_agent_to_read preserves failure_rate as fraction (0-1), not percentage (0-100)."""
    # Create agent with metrics that will produce 44% failure rate
    agent = create_test_agent()
    now = datetime.now(timezone.utc)

    # 44 failures out of 100 total = 0.44 failure rate
    agent.metrics = [
        A2AAgentMetric(response_time=1.0, is_success=True, timestamp=now) for _ in range(56)
    ] + [A2AAgentMetric(response_time=1.0, is_success=False, timestamp=now) for _ in range(44)]

    # Pass team_map={} to avoid DB query for team name
    result = a2a_service.convert_agent_to_read(agent, include_metrics=True, db=mock_db, team_map={})

    # Verify failure_rate is preserved as fraction (0.44), not converted to percentage (44.0)
    assert result.metrics is not None
    assert result.metrics.failure_rate == 0.44


def test_convert_agent_to_read_metrics_empty_agent(mock_db, a2a_service):
    """Test convert_agent_to_read handles empty metrics (no invocations) correctly."""
    # Create agent with no metrics
    agent = create_test_agent()
    agent.metrics = []

    # Pass team_map={} to avoid DB query for team name
    result = a2a_service.convert_agent_to_read(agent, include_metrics=True, db=mock_db, team_map={})

    # Verify metrics are zero/None appropriately
    assert result.metrics is not None
    assert result.metrics.total_executions == 0
    assert result.metrics.successful_executions == 0
    assert result.metrics.failed_executions == 0
    assert result.metrics.failure_rate == 0.0
    assert result.metrics.min_response_time is None
    assert result.metrics.max_response_time is None
    assert result.metrics.avg_response_time is None
    assert result.metrics.last_execution_time is None


def test_convert_agent_to_read_metrics_with_db_session(a2a_service):
    """Integration test: convert_agent_to_read with real DB agent and metrics.

    Note: This test uses a real A2AAgent object with pre-loaded metrics to verify
    the end-to-end flow works correctly.
    """
    # Create agent using helper function
    agent = create_test_agent()
    agent.id = "integration-test-agent"
    agent.name = "Integration Test Agent"

    # Add pre-loaded metrics
    now = datetime.now(timezone.utc)
    agent.metrics = [
        A2AAgentMetric(response_time=1.0, is_success=True, timestamp=now),
        A2AAgentMetric(response_time=2.0, is_success=False, timestamp=now),
        A2AAgentMetric(response_time=1.5, is_success=True, timestamp=now),
    ]

    # Create a mock DB session (not actually needed since metrics are pre-loaded)
    mock_db = MagicMock(spec=Session)

    # Call convert_agent_to_read with include_metrics=True
    # Pass team_map={} to avoid DB query for team name
    result = a2a_service.convert_agent_to_read(agent, include_metrics=True, db=mock_db, team_map={})

    # Verify metrics match the actual data
    assert result.metrics is not None
    assert result.metrics.total_executions == 3
    assert result.metrics.successful_executions == 2
    assert result.metrics.failed_executions == 1
    # failure_rate should be 1/3 ≈ 0.333...
    assert abs(result.metrics.failure_rate - (1 / 3)) < 0.001
    assert result.metrics.min_response_time == 1.0
    assert result.metrics.max_response_time == 2.0
    # avg should be (1.0 + 2.0 + 1.5) / 3 = 1.5
    assert result.metrics.avg_response_time == 1.5
    assert result.metrics.last_execution_time == now
