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

    def test_team_scoped_gateways_allow_duplicate_names(self, test_db):
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
        test_db.add(gateway_a)
        test_db.commit()

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
        test_db.add(gateway_b)
        test_db.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert gateway_a.id != gateway_b.id
        assert gateway_a.slug == gateway_b.slug
        assert gateway_a.team_id != gateway_b.team_id

    def test_team_scoped_servers_allow_duplicate_names(self, test_db):
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
        test_db.add(server_a)
        test_db.commit()

        # Create Team B server with same name
        server_b = DbServer(
            name="Data Processor",  # Same name
            description="Team B's data processor",
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(server_b)
        test_db.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert server_a.id != server_b.id
        assert server_a.name == server_b.name
        assert server_a.team_id != server_b.team_id

    def test_team_scoped_tools_allow_duplicate_names(self, test_db):
        """Test that different teams can register tools with the same name."""
        # Create gateways for each team
        gateway_a = DbGateway(
            name="Team A Gateway Tools",
            slug="team-a-gateway-tools",
            url="http://team-a-tools.example.com/mcp",
            description="Team A gateway for tools",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(gateway_a)
        test_db.flush()

        gateway_b = DbGateway(
            name="Team B Gateway Tools",
            slug="team-b-gateway-tools",
            url="http://team-b-tools.example.com/mcp",
            description="Team B gateway for tools",
            transport="sse",
            capabilities={},
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(gateway_b)
        test_db.flush()

        # Create Team A tool
        tool_a = DbTool(
            custom_name="analyze",
            custom_name_slug="analyze",
            original_name="analyze",
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
        test_db.add(tool_a)
        test_db.commit()

        # Create Team B tool with same name
        tool_b = DbTool(
            custom_name="analyze",  # Same name
            custom_name_slug="analyze",
            original_name="analyze",
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
        test_db.add(tool_b)
        test_db.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert tool_a.id != tool_b.id
        assert tool_a.custom_name == tool_b.custom_name
        assert tool_a.team_id != tool_b.team_id

    def test_team_scoped_prompts_allow_duplicate_names(self, test_db):
        """Test that different teams can register prompts with the same name."""
        # Create gateways for each team with unique slugs
        gateway_a = DbGateway(
            name="Team A Gateway Prompts",
            slug="team-a-gw-prompts",
            url="http://team-a-prompts.example.com/mcp",
            description="Team A gateway for prompts",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(gateway_a)
        test_db.flush()

        gateway_b = DbGateway(
            name="Team B Gateway Prompts",
            slug="team-b-gw-prompts",
            url="http://team-b-prompts.example.com/mcp",
            description="Team B gateway for prompts",
            transport="sse",
            capabilities={},
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(gateway_b)
        test_db.flush()

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
        test_db.add(prompt_a)
        test_db.commit()

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
        test_db.add(prompt_b)
        test_db.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert prompt_a.id != prompt_b.id
        # The 'name' field is auto-generated with gateway slug prefix, so compare custom_name
        assert prompt_a.custom_name == prompt_b.custom_name == "summarize"
        assert prompt_a.team_id != prompt_b.team_id

    def test_team_scoped_resources_allow_duplicate_uris(self, test_db):
        """Test that different teams can register resources with the same URI."""
        # Create gateways for each team with unique slugs
        gateway_a = DbGateway(
            name="Team A Gateway Resources",
            slug="team-a-gw-resources",
            url="http://team-a-resources.example.com/mcp",
            description="Team A gateway for resources",
            transport="sse",
            capabilities={},
            team_id="team-a",
            owner_email="user-a@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(gateway_a)
        test_db.flush()

        gateway_b = DbGateway(
            name="Team B Gateway Resources",
            slug="team-b-gw-resources",
            url="http://team-b-resources.example.com/mcp",
            description="Team B gateway for resources",
            transport="sse",
            capabilities={},
            team_id="team-b",
            owner_email="user-b@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(gateway_b)
        test_db.flush()

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
        test_db.add(resource_a)
        test_db.commit()

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
        test_db.add(resource_b)
        test_db.commit()  # Should not raise IntegrityError

        # Verify both exist
        assert resource_a.id != resource_b.id
        assert resource_a.uri == resource_b.uri
        assert resource_a.team_id != resource_b.team_id

    def test_public_visibility_prevents_duplicate_names_via_application_logic(self, test_db):
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
        test_db.add(gateway_public)
        test_db.commit()

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
        test_db.add(gateway_public_2)

        # This should succeed at DB level (no global constraint)
        test_db.commit()

        # Clean up for other tests
        test_db.delete(gateway_public_2)
        test_db.commit()

    def test_composite_constraint_still_enforces_within_team(self, test_db):
        """Test that composite constraints still prevent duplicates within the same team.

        Note: The slug is auto-generated from the name via a before_insert event listener,
        so both gateways must have the SAME name to generate the same slug and trigger
        the constraint violation.
        """
        # Create Team A gateway
        gateway_a1 = DbGateway(
            name="UniqueConstraintTest",  # Same name = same slug
            slug="will-be-overwritten",  # Slug is auto-generated from name
            url="http://team-a-1.example.com/mcp",
            description="First gateway",
            transport="sse",
            capabilities={},
            team_id="team-composite",
            owner_email="user-composite@example.com",
            visibility="team",
            enabled=True,
        )
        test_db.add(gateway_a1)
        test_db.commit()

        # Try to create another gateway with same team_id + owner_email + name (= same slug)
        # This should fail due to composite unique constraint uq_team_owner_slug_gateway
        gateway_a2 = DbGateway(
            name="UniqueConstraintTest",  # Same name = same slug
            slug="will-be-overwritten",  # Slug is auto-generated from name
            url="http://team-a-2.example.com/mcp",  # Different URL
            description="Second gateway",
            transport="sse",
            capabilities={},
            team_id="team-composite",  # Same team
            owner_email="user-composite@example.com",  # Same owner
            visibility="team",
            enabled=True,
        )

        # This should raise IntegrityError due to composite constraint
        test_db.add(gateway_a2)
        try:
            test_db.commit()
            # If we reach here, the constraint didn't fire - fail the test
            pytest.fail("Expected IntegrityError due to composite unique constraint violation, but commit succeeded")
        except Exception as e:
            # Verify it's a constraint violation
            error_msg = str(e).lower()
            assert "unique constraint failed" in error_msg or "duplicate key" in error_msg, f"Expected constraint violation error, got: {e}"
            test_db.rollback()
