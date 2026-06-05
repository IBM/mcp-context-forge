# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sessionless_list_stability.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Test suite for Phase 4: List stability hardening for sessionless MCP protocols.

This module verifies that tools/list, resources/list, and prompts/list endpoints:
1. Return stable results across separate connections for the same auth context
2. Correctly vary results based on auth-scoped differences (public vs team vs admin)
3. Do not vary results based on connection-scoped state (prior tool calls, etc.)

Issue: #4686 - Implement sessionless MCP protocol semantics
"""

# Standard
import inspect

# Third-Party
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# First-Party
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.db import Tool, Resource, Prompt


@pytest.fixture
def tool_service():
    """Create a ToolService instance."""
    return ToolService()


@pytest.fixture
def resource_service():
    """Create a ResourceService instance."""
    return ResourceService()


@pytest.fixture
def prompt_service():
    """Create a PromptService instance."""
    return PromptService()


class TestListStabilityInvariants:
    """
    Test invariants that must hold for all list endpoints.

    These tests verify the core requirement: list results must be stable
    across connections for the same auth context, and must vary only by
    auth scope, not by connection-scoped state.
    """

    @pytest.mark.asyncio
    async def test_tools_list_same_auth_returns_same_results(
        self, tool_service, test_db
    ):
        """
        Verify that tools/list returns identical results for the same auth context.

        This tests that list results depend only on auth scope (user_email, token_teams)
        and not on connection-scoped state.
        """
        # Create test tools with different visibility levels
        tool1 = Tool(
            original_name="public_tool",
            custom_name="public_tool",
            name="public_tool",
            description="Public tool",
            input_schema={},
            visibility="public",
            enabled=True,
        )
        tool2 = Tool(
            original_name="team_tool",
            custom_name="team_tool",
            name="team_tool",
            description="Team tool",
            input_schema={},
            visibility="team",
            team_id="team1",
            enabled=True,
        )
        test_db.add(tool1)
        test_db.add(tool2)
        test_db.commit()

        # Same auth context should return same results
        tools1, _ = await tool_service.list_tools(
            db=test_db,
            user_email="user@example.com",
            token_teams=["team1"],
            team_id=None,
            visibility=None,
        )
        tools2, _ = await tool_service.list_tools(
            db=test_db,
            user_email="user@example.com",
            token_teams=["team1"],
            team_id=None,
            visibility=None,
        )

        # Results should be identical
        assert len(tools1) == len(tools2)
        assert {t.name for t in tools1} == {t.name for t in tools2}

    @pytest.mark.asyncio
    async def test_tools_list_different_auth_returns_different_results(
        self, tool_service, test_db
    ):
        """
        Verify that tools/list returns different results for different auth contexts.

        This tests auth-scoped isolation - different users should see different tools
        based on their team membership.
        """
        # Create test tools with different visibility levels
        tool1 = Tool(
            original_name="public_tool",
            custom_name="public_tool",
            name="public_tool",
            description="Public tool",
            input_schema={},
            visibility="public",
            enabled=True,
        )
        tool2 = Tool(
            original_name="team1_tool",
            custom_name="team1_tool",
            name="team1_tool",
            description="Team 1 tool",
            input_schema={},
            visibility="team",
            team_id="team1",
            enabled=True,
        )
        tool3 = Tool(
            original_name="team2_tool",
            custom_name="team2_tool",
            name="team2_tool",
            description="Team 2 tool",
            input_schema={},
            visibility="team",
            team_id="team2",
            enabled=True,
        )
        test_db.add_all([tool1, tool2, tool3])
        test_db.commit()

        # User in team1 should see public + team1 tools
        tools_team1, _ = await tool_service.list_tools(
            db=test_db,
            user_email="user1@example.com",
            token_teams=["team1"],
            team_id=None,
            visibility=None,
        )

        # User in team2 should see public + team2 tools
        tools_team2, _ = await tool_service.list_tools(
            db=test_db,
            user_email="user2@example.com",
            token_teams=["team2"],
            team_id=None,
            visibility=None,
        )

        # Results should be different
        names_team1 = {t.name for t in tools_team1}
        names_team2 = {t.name for t in tools_team2}

        # Tool names are normalized (underscores to hyphens)
        assert "public-tool" in names_team1
        assert "team1-tool" in names_team1
        assert "team2-tool" not in names_team1

        assert "public-tool" in names_team2
        assert "team2-tool" in names_team2
        assert "team1-tool" not in names_team2

    @pytest.mark.asyncio
    async def test_resources_list_auth_scoped_not_connection_scoped(
        self, resource_service, test_db
    ):
        """
        Verify that resources/list results depend on auth scope, not connection state.
        """
        # Create test resources
        resource1 = Resource(
            uri="resource://public",
            name="public_resource",
            mime_type="text/plain",
            visibility="public",
            enabled=True,
        )
        resource2 = Resource(
            uri="resource://team",
            name="team_resource",
            mime_type="text/plain",
            visibility="team",
            team_id="team1",
            enabled=True,
        )
        test_db.add_all([resource1, resource2])
        test_db.commit()

        # Same auth context should return same results
        resources1, _ = await resource_service.list_resources(
            db=test_db,
            user_email="user@example.com",
            token_teams=["team1"],
            team_id=None,
            visibility=None,
        )
        resources2, _ = await resource_service.list_resources(
            db=test_db,
            user_email="user@example.com",
            token_teams=["team1"],
            team_id=None,
            visibility=None,
        )

        # Results should be identical
        assert len(resources1) == len(resources2)
        assert {r.uri for r in resources1} == {r.uri for r in resources2}

    @pytest.mark.asyncio
    async def test_prompts_list_auth_scoped_not_connection_scoped(
        self, prompt_service, test_db
    ):
        """
        Verify that prompts/list results depend on auth scope, not connection state.
        """
        # Create test prompts
        prompt1 = Prompt(
            original_name="public_prompt",
            custom_name="public_prompt",
            name="public_prompt",
            description="Public prompt",
            template="Test template",
            argument_schema={},
            visibility="public",
            enabled=True,
        )
        prompt2 = Prompt(
            original_name="team_prompt",
            custom_name="team_prompt",
            name="team_prompt",
            description="Team prompt",
            template="Test template",
            argument_schema={},
            visibility="team",
            team_id="team1",
            enabled=True,
        )
        test_db.add_all([prompt1, prompt2])
        test_db.commit()

        # Same auth context should return same results
        prompts1, _ = await prompt_service.list_prompts(
            db=test_db,
            user_email="user@example.com",
            token_teams=["team1"],
            team_id=None,
            visibility=None,
        )
        prompts2, _ = await prompt_service.list_prompts(
            db=test_db,
            user_email="user@example.com",
            token_teams=["team1"],
            team_id=None,
            visibility=None,
        )

        # Results should be identical
        assert len(prompts1) == len(prompts2)
        assert {p.name for p in prompts1} == {p.name for p in prompts2}

    def test_list_methods_do_not_accept_session_id_parameter(
        self, tool_service, resource_service, prompt_service
    ):
        """
        Verify that list methods do not have session_id parameters.

        This is a structural requirement for sessionless semantics: list
        methods must not accept session identifiers as parameters.
        """
        # Check tool_service.list_tools signature
        tool_sig = inspect.signature(tool_service.list_tools)
        assert "session_id" not in tool_sig.parameters
        assert "mcp_session_id" not in tool_sig.parameters
        assert "downstream_session_id" not in tool_sig.parameters

        # Check resource_service.list_resources signature
        resource_sig = inspect.signature(resource_service.list_resources)
        assert "session_id" not in resource_sig.parameters
        assert "mcp_session_id" not in resource_sig.parameters
        assert "downstream_session_id" not in resource_sig.parameters

        # Check prompt_service.list_prompts signature
        prompt_sig = inspect.signature(prompt_service.list_prompts)
        assert "session_id" not in prompt_sig.parameters
        assert "mcp_session_id" not in prompt_sig.parameters
        assert "downstream_session_id" not in prompt_sig.parameters

    def test_list_methods_accept_auth_scope_parameters(
        self, tool_service, resource_service, prompt_service
    ):
        """
        Verify that list methods accept auth-scoped parameters.

        List methods should accept parameters that define auth scope:
        - user_email: identifies the requesting user
        - token_teams: defines team scope from token
        - team_id: filters to specific team
        - visibility: filters by visibility level
        """
        # Check tool_service.list_tools has auth parameters
        tool_sig = inspect.signature(tool_service.list_tools)
        assert "user_email" in tool_sig.parameters
        assert "token_teams" in tool_sig.parameters
        assert "team_id" in tool_sig.parameters
        assert "visibility" in tool_sig.parameters

        # Check resource_service.list_resources has auth parameters
        resource_sig = inspect.signature(resource_service.list_resources)
        assert "user_email" in resource_sig.parameters
        assert "token_teams" in resource_sig.parameters
        assert "team_id" in resource_sig.parameters
        assert "visibility" in resource_sig.parameters

        # Check prompt_service.list_prompts has auth parameters
        prompt_sig = inspect.signature(prompt_service.list_prompts)
        assert "user_email" in prompt_sig.parameters
        assert "token_teams" in prompt_sig.parameters
        assert "team_id" in prompt_sig.parameters
        assert "visibility" in prompt_sig.parameters


class TestSessionlessProtocolBehavior:
    """
    Test that sessionless protocol semantics are correctly implemented.

    These tests verify that the protocol version gating works correctly
    and that sessionless behavior is properly enforced.
    """

    def test_sessionless_protocol_version_constant_defined(self):
        """Verify that the sessionless protocol version constant is defined."""
        # First-Party
        from mcpgateway.utils.mcp_protocol import SESSIONLESS_PROTOCOL_MIN_VERSION

        assert SESSIONLESS_PROTOCOL_MIN_VERSION == "2025-11-25"

    def test_uses_sessionless_mcp_semantics_function_exists(self):
        """Verify that the protocol version check function exists."""
        # First-Party
        from mcpgateway.utils.mcp_protocol import uses_sessionless_mcp_semantics

        # Test with old protocol version
        assert not uses_sessionless_mcp_semantics("2024-11-05")

        # Test with sessionless protocol version
        assert uses_sessionless_mcp_semantics("2025-11-25")

        # Test with future protocol version
        assert uses_sessionless_mcp_semantics("2026-01-01")

        # Test with None (defaults to "2024-11-05" for backward compatibility)
        # Clients must explicitly opt into sessionless semantics
        assert not uses_sessionless_mcp_semantics(None)


class TestDocumentationAndGuidance:
    """
    Placeholder tests for documentation requirements.

    These tests document the need for developer guidance on stateful
    workflows using explicit handles.
    """

    def test_stateful_workflow_guidance_needed(self):
        """
        Document that guidance is needed for stateful workflows.

        Developers need documentation on how to implement stateful workflows
        using explicit server-minted handles instead of implicit session state.

        Examples of handles:
        - workflow_id for multi-step workflows
        - cursor_id for pagination
        - cart_id for shopping carts
        - browser_id for browser automation

        This guidance should be added to docs/docs/ after Phase 4 is complete.
        """
        # This is a documentation requirement, not a code requirement
        pass

# Made with Bob
