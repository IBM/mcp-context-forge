# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_authorization_access.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for A2A service-layer authorization access checks.

These tests verify the security fixes for issue #4437:
- A2A server access control (a2a_server_service._check_server_access)
- A2A agent visibility in list_tasks (_visible_agent_ids)
- Admin bypass logic alignment with PR #4341
"""

# Standard
from unittest.mock import MagicMock, Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Server as DbServer
from mcpgateway.services.a2a_server_service import _check_server_access
from mcpgateway.services.a2a_service import A2AAgentService


def create_mock_server(visibility="public", owner_email=None, team_id=None, enabled=True):
    """Helper to create mock server with specified visibility."""
    server = MagicMock(spec=DbServer)
    server.id = "server-123"
    server.name = "test_server"
    server.visibility = visibility
    server.owner_email = owner_email
    server.team_id = team_id
    server.enabled = enabled
    server.description = "A test server"
    return server


def create_mock_agent(visibility="public", owner_email=None, team_id=None, enabled=True):
    """Helper to create mock A2A agent with specified visibility."""
    agent = MagicMock(spec=DbA2AAgent)
    agent.id = "agent-123"
    agent.name = "test_agent"
    agent.visibility = visibility
    agent.owner_email = owner_email
    agent.team_id = team_id
    agent.enabled = enabled
    agent.description = "A test agent"
    return agent


class TestA2AServerAccessChecks:
    """Tests for A2A server access authorization (_check_server_access)."""

    def test_public_server_accessible_to_anyone(self):
        """Public servers should be accessible without authentication."""
        mock_server = create_mock_server(visibility="public")

        # Test: unauthenticated user
        result = _check_server_access(mock_server, user_email=None, token_teams=[])
        assert result is True

        # Test: authenticated user from different team
        result = _check_server_access(mock_server, user_email="other@example.com", token_teams=["other-team"])
        assert result is True

    def test_private_server_denied_to_unauthenticated(self):
        """Private servers should not be accessible without authentication."""
        mock_server = create_mock_server(visibility="private", owner_email="owner@example.com")

        result = _check_server_access(mock_server, user_email=None, token_teams=[])
        assert result is False

    def test_private_server_accessible_to_owner(self):
        """Private servers should be accessible to the owner when token allows team access."""
        mock_server = create_mock_server(visibility="private", owner_email="owner@example.com")

        # Owner with explicit non-empty token_teams - owner check applies
        result = _check_server_access(mock_server, user_email="owner@example.com", token_teams=["some-team"])
        assert result is True

    def test_private_server_denied_to_owner_with_public_only_token(self):
        """Private servers should NOT be accessible to owner if they have a public-only token."""
        mock_server = create_mock_server(visibility="private", owner_email="owner@example.com")

        # Owner with a public-only token (token_teams=[]) should be denied
        result = _check_server_access(mock_server, user_email="owner@example.com", token_teams=[])
        assert result is False

    def test_private_server_denied_to_non_owner(self):
        """Private servers should not be accessible to non-owners."""
        mock_server = create_mock_server(visibility="private", owner_email="owner@example.com")

        # Non-owner with explicit non-empty token_teams - should still be denied
        result = _check_server_access(mock_server, user_email="other@example.com", token_teams=["some-team"])
        assert result is False

    def test_team_server_accessible_to_team_member(self):
        """Team-visibility servers should be accessible to team members."""
        mock_server = create_mock_server(visibility="team", owner_email="owner@example.com", team_id="team-abc")

        # User is a member of team-abc via token_teams
        result = _check_server_access(mock_server, user_email="member@example.com", token_teams=["team-abc"])
        assert result is True

    def test_team_server_denied_to_non_member(self):
        """Team-visibility servers should not be accessible to non-team members."""
        mock_server = create_mock_server(visibility="team", owner_email="owner@example.com", team_id="team-abc")

        # User is not a member of team-abc
        result = _check_server_access(mock_server, user_email="outsider@example.com", token_teams=["other-team"])
        assert result is False

    def test_admin_bypass_denied_for_private_servers(self):
        """Admin bypass does NOT grant access to private servers (PR #4341 requirement)."""
        mock_server = create_mock_server(visibility="private", owner_email="owner@example.com", team_id="team-abc")

        # Admin bypass: both user_email and token_teams are None
        # Private servers are NEVER accessible via admin bypass
        result = _check_server_access(mock_server, user_email=None, token_teams=None)
        assert result is False

    def test_admin_bypass_grants_access_to_team_servers(self):
        """Admin bypass grants access to team and public servers, but not private."""
        # Test team visibility
        team_server = create_mock_server(visibility="team", owner_email="owner@example.com", team_id="team-abc")
        result = _check_server_access(team_server, user_email=None, token_teams=None)
        assert result is True

    def test_public_only_token_denied_private_access(self):
        """Tokens with empty teams list should only access public servers."""
        mock_server = create_mock_server(visibility="private", owner_email="owner@example.com")

        # Public-only token: token_teams=[] (explicit empty list)
        result = _check_server_access(mock_server, user_email="user@example.com", token_teams=[])
        assert result is False


class TestA2AVisibleAgentIds:
    """Tests for A2A agent visibility in list_tasks (_visible_agent_ids)."""

    @pytest.fixture
    def a2a_service(self):
        """Create an A2A service instance."""
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock()
        db.commit = Mock()
        return db

    def test_admin_bypass_excludes_private_agents(self, a2a_service, mock_db):
        """Admin bypass should return public + team agents only, excluding private (PR #4341)."""
        # Create mock agents with different visibilities
        public_agent = create_mock_agent(visibility="public")
        public_agent.id = "public-1"
        team_agent = create_mock_agent(visibility="team", team_id="team-abc")
        team_agent.id = "team-1"
        private_agent = create_mock_agent(visibility="private", owner_email="owner@example.com")
        private_agent.id = "private-1"

        # Mock the query to return all agents
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [(public_agent.id,), (team_agent.id,)]  # Private excluded
        mock_db.query.return_value = mock_query

        # Admin bypass: user_email=None, token_teams=None
        result = a2a_service._visible_agent_ids(mock_db, user_email=None, token_teams=None)

        # Should return list of IDs (not None), excluding private agents
        assert result is not None
        assert isinstance(result, list)
        assert "public-1" in result
        assert "team-1" in result
        assert "private-1" not in result

        # Verify the query was filtered to public + team only
        filter_calls = mock_query.filter.call_args_list
        assert len(filter_calls) >= 1
        all_compiled = " ".join(
            str(arg.compile(compile_kwargs={"literal_binds": True}))
            for c in filter_calls
            for arg in c.args
        )
        assert "visibility" in all_compiled
        assert "public" in all_compiled or "'public'" in all_compiled
        assert "team" in all_compiled or "'team'" in all_compiled

    def test_public_only_token_returns_public_agents(self, a2a_service, mock_db):
        """Public-only token (token_teams=[]) should only see public agents."""
        public_agent = create_mock_agent(visibility="public")
        public_agent.id = "public-1"

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [(public_agent.id,)]
        mock_db.query.return_value = mock_query

        # Public-only token
        result = a2a_service._visible_agent_ids(mock_db, user_email="user@example.com", token_teams=[])

        assert result is not None
        assert isinstance(result, list)
        # The actual filtering happens in the query, we just verify it returns a list

        filter_calls = mock_query.filter.call_args_list
        assert len(filter_calls) >= 1
        all_compiled = " ".join(
            str(arg.compile(compile_kwargs={"literal_binds": True}))
            for c in filter_calls
            for arg in c.args
        )
        assert "visibility" in all_compiled
        assert "public" in all_compiled or "'public'" in all_compiled

    def test_team_scoped_token_returns_team_and_public_agents(self, a2a_service, mock_db):
        """Team-scoped token should see public + team agents."""
        public_agent = create_mock_agent(visibility="public")
        public_agent.id = "public-1"
        team_agent = create_mock_agent(visibility="team", team_id="team-abc")
        team_agent.id = "team-1"

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [(public_agent.id,), (team_agent.id,)]
        mock_db.query.return_value = mock_query

        # Team-scoped token
        result = a2a_service._visible_agent_ids(mock_db, user_email="user@example.com", token_teams=["team-abc"])

        assert result is not None
        assert isinstance(result, list)

        filter_calls = mock_query.filter.call_args_list
        assert len(filter_calls) >= 1
        all_compiled = " ".join(
            str(arg.compile(compile_kwargs={"literal_binds": True}))
            for c in filter_calls
            for arg in c.args
        )
        assert "visibility" in all_compiled
        assert "team_id" in all_compiled


class TestA2AListTasksFiltering:
    """Integration tests for list_tasks with admin bypass."""

    @pytest.fixture
    def a2a_service(self):
        """Create an A2A service instance."""
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock()
        db.commit = Mock()
        return db

    def test_list_tasks_admin_bypass_excludes_private_agent_tasks(self, a2a_service, mock_db):
        """list_tasks with admin bypass should not return tasks from private agents."""
        # Mock _visible_agent_ids to return only public/team agents
        mock_agent_query = MagicMock()
        mock_agent_query.filter.return_value = mock_agent_query
        mock_agent_query.all.return_value = [("public-agent-1",), ("team-agent-1",)]

        # Mock the task query
        mock_task_query = MagicMock()
        mock_task_query.filter.return_value = mock_task_query
        mock_task_query.order_by.return_value = mock_task_query
        mock_task_query.limit.return_value = mock_task_query
        mock_task_query.offset.return_value = mock_task_query
        mock_task_query.all.return_value = []

        # Track which query is being created
        query_call_count = [0]

        def query_side_effect(_model_or_column):
            query_call_count[0] += 1
            # First call is for _visible_agent_ids (DbA2AAgent.id)
            if query_call_count[0] == 1:
                return mock_agent_query
            # Second call is for tasks (A2ATask)
            return mock_task_query

        mock_db.query.side_effect = query_side_effect

        # Call list_tasks with admin bypass
        result = a2a_service.list_tasks(
            mock_db,
            user_email=None,
            token_teams=None,
            limit=100,
            offset=0
        )

        assert any("IN" in str(arg) for call in mock_task_query.filter.call_args_list for arg in call.args), "Task query should filter by agent IDs"

        # Verify that _visible_agent_ids was called and returned a filtered list
        assert isinstance(result, list)
        # Verify db.query was called at least twice (once for agents, once for tasks)
        assert query_call_count[0] >= 2
        # The key assertion is that _visible_agent_ids returns a list (not None)
        # which means the task query will be filtered by agent IDs
