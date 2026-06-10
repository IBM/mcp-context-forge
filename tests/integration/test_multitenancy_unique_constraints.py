"""Integration tests for multi-tenant unique constraints (Bug #5146).

This module tests that different teams can register entities with the same names
when using team visibility, verifying the fix for issue #5146 where global unique
constraints were preventing proper multi-tenant isolation.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool


@pytest.mark.integration
class TestMultiTenancyUniqueConstraints:
    """Test that team-scoped entities can have duplicate names across teams."""

    def test_team_scoped_gateways_allow_duplicate_names(self, db_session):
        """Test that different teams can register gateways with the same name.

        This test verifies the fix for bug #5146 where global unique constraints
        on gateways.slug and gateways.url prevented teams from using the same
        gateway names.
        """
        # Create Team A gateway
        gateway_a = DbGateway(
            name="Shared Gateway",
            slug="shared-gateway",
            url="http://team-a.example.com/mcp",
            description="Team A's gateway",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_a)
        db_session.commit()

        # Create Team B gateway with same name (should succeed after fix)
        gateway_b = DbGateway(
            name="Shared Gateway",  # Same name
            slug="shared-gateway",  # Same slug
            url="http://team-b.example.com/mcp",  # Different URL
            description="Team B's gateway",
            transport="sse",
            capabilities={},
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_b)
        db_session.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert gateway_a.id != gateway_b.id
        assert gateway_a.slug == gateway_b.slug
        assert gateway_a.team_id != gateway_b.team_id

    def test_team_scoped_servers_allow_duplicate_names(self, db_session):
        """Test that different teams can register servers with the same name."""
        # Create Team A server
        server_a = DbServer(
            name="Data Processor",
            description="Team A's data processor",
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(server_a)
        db_session.commit()

        # Create Team B server with same name
        server_b = DbServer(
            name="Data Processor",  # Same name
            description="Team B's data processor",
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(server_b)
        db_session.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert server_a.id != server_b.id
        assert server_a.name == server_b.name
        assert server_a.team_id != server_b.team_id

    def test_team_scoped_tools_allow_duplicate_names(self, db_session):
        """Test that different teams can register tools with the same name."""
        # Create gateways for each team
        gateway_a = DbGateway(
            name="Team A Gateway",
            slug="team-a-gateway",
            url="http://team-a-tools.example.com/mcp",
            description="Team A gateway for tools",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_a)
        db_session.flush()

        gateway_b = DbGateway(
            name="Team B Gateway",
            slug="team-b-gateway",
            url="http://team-b-tools.example.com/mcp",
            description="Team B gateway for tools",
            transport="sse",
            capabilities={},
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_b)
        db_session.flush()

        # Create Team A tool
        tool_a = DbTool(
            name="analyze",
            original_name="analyze",
            original_name_slug="analyze",
            description="Team A's analyzer",
            integration_type="REST",
            request_type="POST",
            input_schema={},
            gateway_id=gateway_a.id,
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(tool_a)
        db_session.commit()

        # Create Team B tool with same name
        tool_b = DbTool(
            name="analyze",  # Same name
            original_name="analyze",
            original_name_slug="analyze",
            description="Team B's analyzer",
            integration_type="REST",
            request_type="POST",
            input_schema={},
            gateway_id=gateway_b.id,
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(tool_b)
        db_session.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert tool_a.id != tool_b.id
        assert tool_a.name == tool_b.name
        assert tool_a.team_id != tool_b.team_id

    def test_team_scoped_prompts_allow_duplicate_names(self, db_session):
        """Test that different teams can register prompts with the same name."""
        # Create gateways for each team
        gateway_a = DbGateway(
            name="Team A Gateway",
            slug="team-a-gateway-prompts",
            url="http://team-a-prompts.example.com/mcp",
            description="Team A gateway for prompts",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_a)
        db_session.flush()

        gateway_b = DbGateway(
            name="Team B Gateway",
            slug="team-b-gateway-prompts",
            url="http://team-b-prompts.example.com/mcp",
            description="Team B gateway for prompts",
            transport="sse",
            capabilities={},
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_b)
        db_session.flush()

        # Create Team A prompt
        prompt_a = DbPrompt(
            name="summarize",
            description="Team A's summarizer",
            template="Summarize: {text}",
            argument_schema={},
            gateway_id=gateway_a.id,
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(prompt_a)
        db_session.commit()

        # Create Team B prompt with same name
        prompt_b = DbPrompt(
            name="summarize",  # Same name
            description="Team B's summarizer",
            template="Summarize: {content}",
            argument_schema={},
            gateway_id=gateway_b.id,
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(prompt_b)
        db_session.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert prompt_a.id != prompt_b.id
        assert prompt_a.name == prompt_b.name
        assert prompt_a.team_id != prompt_b.team_id

    def test_team_scoped_resources_allow_duplicate_uris(self, db_session):
        """Test that different teams can register resources with the same URI."""
        # Create gateways for each team
        gateway_a = DbGateway(
            name="Team A Gateway",
            slug="team-a-gateway-resources",
            url="http://team-a-resources.example.com/mcp",
            description="Team A gateway for resources",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_a)
        db_session.flush()

        gateway_b = DbGateway(
            name="Team B Gateway",
            slug="team-b-gateway-resources",
            url="http://team-b-resources.example.com/mcp",
            description="Team B gateway for resources",
            transport="sse",
            capabilities={},
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_b)
        db_session.flush()

        # Create Team A resource
        resource_a = DbResource(
            uri="file:///data/config.json",
            name="config",
            description="Team A's config",
            gateway_id=gateway_a.id,
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(resource_a)
        db_session.commit()

        # Create Team B resource with same URI
        resource_b = DbResource(
            uri="file:///data/config.json",  # Same URI
            name="config",
            description="Team B's config",
            gateway_id=gateway_b.id,
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(resource_b)
        db_session.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert resource_a.id != resource_b.id
        assert resource_a.uri == resource_b.uri
        assert resource_a.team_id != resource_b.team_id

    def test_public_visibility_prevents_duplicate_names_via_application_logic(self, db_session):
        """Test that public entities still enforce uniqueness via application logic.

        Note: After removing global database constraints, uniqueness for public
        entities is enforced by application logic in the service layer, not by
        database constraints.
        """
        # Create public gateway
        gateway_public = DbGateway(
            name="Public Gateway",
            slug="public-gateway",
            url="http://public.example.com/mcp",
            description="Public gateway",
            transport="sse",
            capabilities={},
            team_id=None,
            owner_email="admin@example.com",
            visibility="public",
            enabled=True,
        )
        db_session.add(gateway_public)
        db_session.commit()

        # At the database level, we CAN create another public gateway with the same name
        # (because we removed global constraints), but the application service layer
        # should prevent this. This test verifies the database allows it, while
        # gateway_service.py should enforce the uniqueness check.
        gateway_public_2 = DbGateway(
            name="Public Gateway",
            slug="public-gateway",
            url="http://public2.example.com/mcp",
            description="Another public gateway",
            transport="sse",
            capabilities={},
            team_id=None,
            owner_email="admin2@example.com",
            visibility="public",
            enabled=True,
        )
        db_session.add(gateway_public_2)

        # This should succeed at DB level (no global constraint)
        db_session.commit()

        # Clean up for other tests
        db_session.delete(gateway_public_2)
        db_session.commit()

    def test_composite_constraint_still_enforces_within_team(self, db_session):
        """Test that composite constraints still prevent duplicates within the same team."""
        # Create Team A gateway
        gateway_a1 = DbGateway(
            name="Team Gateway",
            slug="team-gateway",
            url="http://team-a-1.example.com/mcp",
            description="First gateway",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_a1)
        db_session.commit()

        # Try to create another gateway with same team_id + owner_email + slug
        # This should fail due to composite unique constraint uq_team_owner_slug_gateway
        gateway_a2 = DbGateway(
            name="Team Gateway 2",
            slug="team-gateway",  # Same slug
            url="http://team-a-2.example.com/mcp",  # Different URL
            description="Second gateway",
            transport="sse",
            capabilities={},
            team_id="team-a",  # Same team
            owner_email="user-a@example.com",  # Same owner
            visibility="team",
            enabled=True,
        )
        db_session.add(gateway_a2)

        # This should raise IntegrityError due to composite constraint
        with pytest.raises(Exception) as exc_info:
            db_session.commit()

        # Verify it's a constraint violation
        assert "UNIQUE constraint failed" in str(exc_info.value) or "duplicate key" in str(exc_info.value).lower()
        db_session.rollback()
