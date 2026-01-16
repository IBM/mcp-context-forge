# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_authorization_access.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for service-layer authorization access checks.

These tests verify the security fixes for:
- Cross-tenant tool/resource/prompt access prevention
- Admin bypass logic
- Server scoping enforcement
- Unauthenticated request filtering
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.prompt_service import PromptNotFoundError, PromptService
from mcpgateway.services.resource_service import ResourceNotFoundError, ResourceService
from mcpgateway.services.tool_service import ToolNotFoundError, ToolService


@pytest.fixture
def tool_service():
    """Create a tool service instance."""
    service = ToolService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def resource_service():
    """Create a resource service instance."""
    return ResourceService()


@pytest.fixture
def prompt_service():
    """Create a prompt service instance."""
    return PromptService()


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    db.commit = Mock()
    return db


def create_mock_tool(visibility="public", owner_email=None, team_id=None, enabled=True):
    """Helper to create mock tool with specified visibility."""
    tool = MagicMock(spec=DbTool)
    tool.id = "tool-123"
    tool.name = "test_tool"
    tool.original_name = "test_tool"
    tool.visibility = visibility
    tool.owner_email = owner_email
    tool.team_id = team_id
    tool.enabled = enabled
    tool.reachable = True
    tool.integration_type = "REST"
    tool.request_type = "GET"
    tool.url = "http://example.com/tools/test"
    tool.headers = {}
    tool.input_schema = {"type": "object", "properties": {}}
    tool.output_schema = None
    tool.auth_type = None
    tool.auth_value = None
    tool.oauth_config = None
    tool.gateway_id = None
    tool.gateway = None
    tool.jsonpath_filter = ""
    tool.annotations = {}
    tool.tags = []
    tool.custom_name = None
    tool.custom_name_slug = None
    tool.display_name = None
    tool.description = "A test tool"
    return tool


def create_mock_resource(visibility="public", owner_email=None, team_id=None, enabled=True):
    """Helper to create mock resource with specified visibility."""
    resource = MagicMock(spec=DbResource)
    resource.id = "resource-123"
    resource.uri = "file://test.txt"
    resource.name = "Test Resource"
    resource.visibility = visibility
    resource.owner_email = owner_email
    resource.team_id = team_id
    resource.enabled = enabled
    resource.mimeType = "text/plain"
    resource.integration_type = "STATIC"
    resource.static_content = "Test content"
    resource.gateway_id = None
    return resource


def create_mock_prompt(visibility="public", owner_email=None, team_id=None, enabled=True):
    """Helper to create mock prompt with specified visibility."""
    prompt = MagicMock(spec=DbPrompt)
    prompt.id = "prompt-123"
    prompt.name = "test_prompt"
    prompt.visibility = visibility
    prompt.owner_email = owner_email
    prompt.team_id = team_id
    prompt.enabled = enabled
    prompt.description = "A test prompt"
    prompt.arguments = []
    prompt.messages = [{"role": "user", "content": {"type": "text", "text": "Hello"}}]
    prompt.gateway_id = None
    return prompt


class TestToolAccessChecks:
    """Tests for tool access authorization."""

    @pytest.mark.asyncio
    async def test_public_tool_accessible_to_anyone(self, tool_service, mock_db):
        """Public tools should be accessible without authentication."""
        mock_tool = create_mock_tool(visibility="public")

        # Use a tool_payload dict as that's what _check_tool_access expects
        tool_payload = {
            "id": mock_tool.id,
            "visibility": mock_tool.visibility,
            "owner_email": mock_tool.owner_email,
            "team_id": mock_tool.team_id,
        }

        # Test: unauthenticated user
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email=None, token_teams=[])
        assert result is True

        # Test: authenticated user from different team
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email="other@example.com", token_teams=["other-team"])
        assert result is True

    @pytest.mark.asyncio
    async def test_private_tool_denied_to_unauthenticated(self, tool_service, mock_db):
        """Private tools should not be accessible without authentication."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "private",
            "owner_email": "owner@example.com",
            "team_id": None,
        }

        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email=None, token_teams=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_private_tool_accessible_to_owner(self, tool_service, mock_db):
        """Private tools should be accessible to the owner when token allows team access."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "private",
            "owner_email": "owner@example.com",
            "team_id": None,
        }

        # Owner with explicit non-empty token_teams - owner check applies
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email="owner@example.com", token_teams=["some-team"])
        assert result is True

    @pytest.mark.asyncio
    async def test_private_tool_denied_to_owner_with_public_only_token(self, tool_service, mock_db):
        """Private tools should NOT be accessible to owner if they have a public-only token."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "private",
            "owner_email": "owner@example.com",
            "team_id": None,
        }

        # Owner with a public-only token (token_teams=[]) should be denied
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email="owner@example.com", token_teams=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_private_tool_denied_to_non_owner(self, tool_service, mock_db):
        """Private tools should not be accessible to non-owners."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "private",
            "owner_email": "owner@example.com",
            "team_id": None,
        }

        # Non-owner with explicit non-empty token_teams - should still be denied
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email="other@example.com", token_teams=["some-team"])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_tool_accessible_to_team_member(self, tool_service, mock_db):
        """Team-visibility tools should be accessible to team members."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "team",
            "owner_email": "owner@example.com",
            "team_id": "team-abc",
        }

        # User is a member of team-abc via token_teams
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email="member@example.com", token_teams=["team-abc"])
        assert result is True

    @pytest.mark.asyncio
    async def test_team_tool_denied_to_non_member(self, tool_service, mock_db):
        """Team-visibility tools should not be accessible to non-team members."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "team",
            "owner_email": "owner@example.com",
            "team_id": "team-abc",
        }

        # User is not a member of team-abc
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email="outsider@example.com", token_teams=["other-team"])
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_bypass_grants_full_access(self, tool_service, mock_db):
        """Admins with token_teams=None and user_email=None should have full access."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "private",
            "owner_email": "owner@example.com",
            "team_id": "team-abc",
        }

        # Admin bypass: both user_email and token_teams are None
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email=None, token_teams=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_public_only_token_denied_private_access(self, tool_service, mock_db):
        """Tokens with empty teams list should only access public tools."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "private",
            "owner_email": "owner@example.com",
            "team_id": None,
        }

        # Public-only token: token_teams=[] (explicit empty list)
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email="user@example.com", token_teams=[])
        assert result is False


class TestResourceAccessChecks:
    """Tests for resource access authorization."""

    @pytest.mark.asyncio
    async def test_public_resource_accessible_to_anyone(self, resource_service, mock_db):
        """Public resources should be accessible without authentication."""
        mock_resource = create_mock_resource(visibility="public")

        # Test: unauthenticated user
        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email=None, token_teams=[])
        assert result is True

    @pytest.mark.asyncio
    async def test_private_resource_denied_to_unauthenticated(self, resource_service, mock_db):
        """Private resources should not be accessible without authentication."""
        mock_resource = create_mock_resource(visibility="private", owner_email="owner@example.com")

        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email=None, token_teams=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_private_resource_accessible_to_owner(self, resource_service, mock_db):
        """Private resources should be accessible to the owner when token allows."""
        mock_resource = create_mock_resource(visibility="private", owner_email="owner@example.com")

        # Owner with explicit team list (not empty) - owner check applies
        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email="owner@example.com", token_teams=["some-team"])
        assert result is True

    @pytest.mark.asyncio
    async def test_private_resource_denied_to_owner_with_public_only_token(self, resource_service, mock_db):
        """Private resources should NOT be accessible to owner with public-only token."""
        mock_resource = create_mock_resource(visibility="private", owner_email="owner@example.com")

        # Owner with public-only token should be denied
        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email="owner@example.com", token_teams=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_resource_accessible_to_team_member(self, resource_service, mock_db):
        """Team-visibility resources should be accessible to team members."""
        mock_resource = create_mock_resource(visibility="team", owner_email="owner@example.com", team_id="team-abc")

        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email="member@example.com", token_teams=["team-abc"])
        assert result is True

    @pytest.mark.asyncio
    async def test_team_resource_denied_to_non_member(self, resource_service, mock_db):
        """Team-visibility resources should not be accessible to non-team members."""
        mock_resource = create_mock_resource(visibility="team", owner_email="owner@example.com", team_id="team-abc")

        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email="outsider@example.com", token_teams=["other-team"])
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_bypass_grants_full_access(self, resource_service, mock_db):
        """Admins with token_teams=None and user_email=None should have full access."""
        mock_resource = create_mock_resource(visibility="private", owner_email="owner@example.com", team_id="team-abc")

        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email=None, token_teams=None)
        assert result is True


class TestPromptAccessChecks:
    """Tests for prompt access authorization."""

    @pytest.mark.asyncio
    async def test_public_prompt_accessible_to_anyone(self, prompt_service, mock_db):
        """Public prompts should be accessible without authentication."""
        mock_prompt = create_mock_prompt(visibility="public")

        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email=None, token_teams=[])
        assert result is True

    @pytest.mark.asyncio
    async def test_private_prompt_denied_to_unauthenticated(self, prompt_service, mock_db):
        """Private prompts should not be accessible without authentication."""
        mock_prompt = create_mock_prompt(visibility="private", owner_email="owner@example.com")

        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email=None, token_teams=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_private_prompt_accessible_to_owner(self, prompt_service, mock_db):
        """Private prompts should be accessible to the owner when token allows."""
        mock_prompt = create_mock_prompt(visibility="private", owner_email="owner@example.com")

        # Owner with explicit team list (not empty) - owner check applies
        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email="owner@example.com", token_teams=["some-team"])
        assert result is True

    @pytest.mark.asyncio
    async def test_private_prompt_denied_to_owner_with_public_only_token(self, prompt_service, mock_db):
        """Private prompts should NOT be accessible to owner with public-only token."""
        mock_prompt = create_mock_prompt(visibility="private", owner_email="owner@example.com")

        # Owner with public-only token should be denied
        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email="owner@example.com", token_teams=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_prompt_accessible_to_team_member(self, prompt_service, mock_db):
        """Team-visibility prompts should be accessible to team members."""
        mock_prompt = create_mock_prompt(visibility="team", owner_email="owner@example.com", team_id="team-abc")

        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email="member@example.com", token_teams=["team-abc"])
        assert result is True

    @pytest.mark.asyncio
    async def test_team_prompt_denied_to_non_member(self, prompt_service, mock_db):
        """Team-visibility prompts should not be accessible to non-team members."""
        mock_prompt = create_mock_prompt(visibility="team", owner_email="owner@example.com", team_id="team-abc")

        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email="outsider@example.com", token_teams=["other-team"])
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_bypass_grants_full_access(self, prompt_service, mock_db):
        """Admins with token_teams=None and user_email=None should have full access."""
        mock_prompt = create_mock_prompt(visibility="private", owner_email="owner@example.com", team_id="team-abc")

        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email=None, token_teams=None)
        assert result is True


class TestInvokeToolAuthorization:
    """Tests for invoke_tool authorization enforcement."""

    @pytest.fixture(autouse=True)
    def reset_tool_lookup_cache(self):
        """Clear tool lookup cache between tests."""
        from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache

        tool_lookup_cache.invalidate_all_local()
        yield
        tool_lookup_cache.invalidate_all_local()

    @pytest.fixture(autouse=True)
    def mock_logging_services(self):
        """Mock audit_trail and structured_logger to prevent database writes during tests."""
        from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache

        clear_ssl_context_cache()
        with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger") as mock_logger:
            mock_audit.log_action = MagicMock(return_value=None)
            mock_logger.log = MagicMock(return_value=None)
            yield

    @pytest.fixture(autouse=True)
    def mock_fresh_db_session(self):
        """Mock fresh_db_session context manager."""
        from contextlib import contextmanager

        @contextmanager
        def mock_fresh_session():
            yield MagicMock()

        with patch("mcpgateway.services.tool_service.fresh_db_session", mock_fresh_session):
            yield

    @pytest.mark.asyncio
    async def test_invoke_tool_denies_cross_tenant_access(self, tool_service, mock_db):
        """User from Team A cannot execute Team B's private tool."""
        mock_tool = create_mock_tool(visibility="private", owner_email="teamb@example.com", team_id="team-b")

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_db.execute = Mock(return_value=mock_scalar)

        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(
                mock_db,
                "test_tool",
                {},
                user_email="teama@example.com",
                token_teams=["team-a"],
            )

        assert "Tool not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_allows_team_member_access(self, tool_service, mock_db):
        """User from Team A can execute Team A's team-visible tool."""
        mock_tool = create_mock_tool(visibility="team", owner_email="owner@example.com", team_id="team-a")

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_db.execute = Mock(return_value=mock_scalar)

        # Mock successful REST call
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "success"})
        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        with patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=MagicMock()):
            result = await tool_service.invoke_tool(
                mock_db,
                "test_tool",
                {},
                user_email="member@example.com",
                token_teams=["team-a"],
            )

        assert result is not None
        assert result.content[0].text is not None

    @pytest.mark.asyncio
    async def test_invoke_tool_admin_bypass_works(self, tool_service, mock_db):
        """Admin with unrestricted token can execute any tool."""
        mock_tool = create_mock_tool(visibility="private", owner_email="secret@example.com", team_id="secret-team")

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_db.execute = Mock(return_value=mock_scalar)

        # Mock successful REST call
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "success"})
        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        with patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=MagicMock()):
            # Admin bypass: user_email=None and token_teams=None
            result = await tool_service.invoke_tool(
                mock_db,
                "test_tool",
                {},
                user_email=None,
                token_teams=None,
            )

        assert result is not None


class TestServerScoping:
    """Tests for server scoping enforcement."""

    @pytest.fixture(autouse=True)
    def reset_tool_lookup_cache(self):
        """Clear tool lookup cache between tests."""
        from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache

        tool_lookup_cache.invalidate_all_local()
        yield
        tool_lookup_cache.invalidate_all_local()

    @pytest.fixture(autouse=True)
    def mock_logging_services(self):
        """Mock audit_trail and structured_logger."""
        from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache

        clear_ssl_context_cache()
        with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger") as mock_logger:
            mock_audit.log_action = MagicMock(return_value=None)
            mock_logger.log = MagicMock(return_value=None)
            yield

    @pytest.fixture(autouse=True)
    def mock_fresh_db_session(self):
        """Mock fresh_db_session context manager."""
        from contextlib import contextmanager

        @contextmanager
        def mock_fresh_session():
            yield MagicMock()

        with patch("mcpgateway.services.tool_service.fresh_db_session", mock_fresh_session):
            yield

    @pytest.mark.asyncio
    async def test_invoke_tool_requires_server_membership(self, tool_service, mock_db):
        """Tool must be attached to server when server_id is provided."""
        mock_tool = create_mock_tool(visibility="public")

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        # First call returns tool, second call (server membership check) returns None
        mock_db.execute = Mock(side_effect=[mock_scalar, MagicMock(first=Mock(return_value=None))])

        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(
                mock_db,
                "test_tool",
                {},
                user_email=None,
                token_teams=None,  # Admin
                server_id="server-123",  # But tool not attached to this server
            )

        assert "Tool not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_denies_when_tool_id_missing(self, tool_service, mock_db):
        """Should deny access when tool has no ID (can't verify server membership)."""
        mock_tool = create_mock_tool(visibility="public")
        mock_tool.id = None  # No ID - will fail server membership check

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_db.execute = Mock(return_value=mock_scalar)

        # The _build_tool_cache_payload will set id to "None" (string), not None
        # So we need to patch it to return a payload with no id
        with patch.object(tool_service, "_build_tool_cache_payload") as mock_build:
            mock_build.return_value = {
                "tool": {
                    "name": "test_tool",
                    "visibility": "public",
                    "enabled": True,
                    "reachable": True,
                    # No "id" key - triggers the denial
                },
                "gateway": None,
            }

            with pytest.raises(ToolNotFoundError) as exc_info:
                await tool_service.invoke_tool(
                    mock_db,
                    "test_tool",
                    {},
                    user_email=None,
                    token_teams=None,
                    server_id="server-123",
                )

            assert "Tool not found" in str(exc_info.value)


class TestCachePoisoningPrevention:
    """Tests to verify cache poisoning prevention in list operations.

    These tests verify that the registry cache is not used when token_teams is set,
    preventing cache poisoning where admin results could leak to public-only requests.
    """

    @pytest.mark.asyncio
    async def test_list_tools_skips_cache_when_token_teams_set(self, tool_service, mock_db):
        """Cache should be skipped when token_teams is set (even empty list)."""
        # Mock the registry cache module to track cache.get calls
        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_get_cache.return_value = mock_cache

            mock_scalars = Mock()
            mock_scalars.all.return_value = []
            mock_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=mock_scalars)))

            # With token_teams=[] (public-only), cache should NOT be used
            await tool_service.list_tools(mock_db, user_email=None, token_teams=[])

            # Cache get should NOT have been called because token_teams was set
            mock_cache.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_tools_uses_cache_when_admin(self, tool_service, mock_db):
        """Cache should be used when token_teams is None (admin unrestricted)."""
        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()  # Also mock cache.set as async
            mock_cache.hash_filters = Mock(return_value="test_hash")
            mock_get_cache.return_value = mock_cache

            mock_scalars = Mock()
            mock_scalars.all.return_value = []
            mock_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=mock_scalars)))

            # With token_teams=None (admin), cache SHOULD be used
            await tool_service.list_tools(mock_db, user_email=None, token_teams=None)

            # Cache get should have been called
            mock_cache.get.assert_called_once()


# Note: list_tools filtering tests are better done as integration tests
# because the visibility filtering happens at the SQL query level in the WHERE clause,
# which is difficult to properly mock at the unit test level.
# The core authorization checks (_check_tool_access, etc.) are tested above.


class TestTemplateResourceAuthorization:
    """Tests for template resource authorization.

    These tests verify that template resources go through the same access checks
    as regular resources. Previously, template resources bypassed access checks
    because _read_template_resource returned content without setting resource_db.
    """

    @pytest.mark.asyncio
    async def test_private_template_resource_denied_to_unauthenticated(self, resource_service, mock_db):
        """Private template resources should be denied to unauthenticated users."""
        # Create a private template resource
        mock_template_resource = create_mock_resource(
            visibility="private",
            owner_email="owner@example.com",
            team_id=None,
        )
        mock_template_resource.id = "template-123"
        mock_template_resource.uri = "file://{filename}"  # Template URI pattern
        mock_template_resource.mime_type = "text/plain"

        # Mock _read_template_resource to return content with ID
        from mcpgateway.common.models import ResourceContent

        mock_content = ResourceContent(
            type="resource",
            id="template-123",
            uri="file://{filename}",
            mime_type="text/plain",
            text="template content",
        )

        # Mock DB queries:
        # 1. First query (by URI) returns None (triggers template path)
        # 2. Template query (by ID) returns the private resource
        call_count = [0]

        def mock_execute(query):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # First call: lookup by URI - not found
                mock_result.scalar_one_or_none.return_value = None
            else:
                # Subsequent calls: lookup by template ID
                mock_result.scalar_one_or_none.return_value = mock_template_resource
                mock_result.first.return_value = None  # No server association
            return mock_result

        mock_db.execute = mock_execute

        # Mock _read_template_resource to return content
        with patch.object(resource_service, "_read_template_resource", new_callable=AsyncMock) as mock_read_template:
            mock_read_template.return_value = mock_content

            # Attempt to read as unauthenticated user (public-only access)
            with pytest.raises(ResourceNotFoundError):
                await resource_service.read_resource(
                    mock_db,
                    resource_uri="file://secret.txt",
                    user=None,
                    token_teams=[],  # Public-only token
                )

    @pytest.mark.asyncio
    async def test_team_template_resource_denied_to_non_member(self, resource_service, mock_db):
        """Team-scoped template resources should be denied to non-team members."""
        # Create a team-scoped template resource
        mock_template_resource = create_mock_resource(
            visibility="team",
            owner_email="owner@example.com",
            team_id="team-abc",
        )
        mock_template_resource.id = "template-456"
        mock_template_resource.uri = "data://{key}"
        mock_template_resource.mime_type = "text/plain"

        from mcpgateway.common.models import ResourceContent

        mock_content = ResourceContent(
            type="resource",
            id="template-456",
            uri="data://{key}",
            mime_type="text/plain",
            text="team data",
        )

        call_count = [0]

        def mock_execute(query):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_result.scalar_one_or_none.return_value = mock_template_resource
                mock_result.first.return_value = None
            return mock_result

        mock_db.execute = mock_execute

        with patch.object(resource_service, "_read_template_resource", new_callable=AsyncMock) as mock_read_template:
            mock_read_template.return_value = mock_content

            # Attempt to read as user NOT in team-abc
            with pytest.raises(ResourceNotFoundError):
                await resource_service.read_resource(
                    mock_db,
                    resource_uri="data://mykey",
                    user="outsider@example.com",
                    token_teams=["other-team"],  # Not team-abc
                )

    @pytest.mark.asyncio
    async def test_team_template_resource_accessible_to_member(self, resource_service, mock_db):
        """Team-scoped template resources should be accessible to team members."""
        # Create a team-scoped template resource
        mock_template_resource = create_mock_resource(
            visibility="team",
            owner_email="owner@example.com",
            team_id="team-abc",
        )
        mock_template_resource.id = "template-789"
        mock_template_resource.uri = "api://{endpoint}"
        mock_template_resource.mime_type = "text/plain"
        mock_template_resource.content = "api response data"

        from mcpgateway.common.models import ResourceContent

        mock_content = ResourceContent(
            type="resource",
            id="template-789",
            uri="api://{endpoint}",
            mime_type="text/plain",
            text="api response data",
        )

        call_count = [0]

        def mock_execute(query):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # First call: lookup by URI - not found
                mock_result.scalar_one_or_none.return_value = None
            elif call_count[0] == 2:
                # Second call: inactivity check - not inactive
                mock_result.scalar_one_or_none.return_value = None
            else:
                # Third+ calls: template lookup by ID
                mock_result.scalar_one_or_none.return_value = mock_template_resource
                mock_result.first.return_value = None
            return mock_result

        mock_db.execute = mock_execute

        with patch.object(resource_service, "_read_template_resource", new_callable=AsyncMock) as mock_read_template:
            mock_read_template.return_value = mock_content

            # Read as team member - should succeed
            result = await resource_service.read_resource(
                mock_db,
                resource_uri="api://users",
                user="member@example.com",
                token_teams=["team-abc"],  # Member of team-abc
            )

            # Should return content (not raise error)
            assert result is not None

    @pytest.mark.asyncio
    async def test_public_template_resource_accessible_to_unauthenticated(self, resource_service, mock_db):
        """Public template resources should be accessible to unauthenticated users."""
        mock_template_resource = create_mock_resource(
            visibility="public",
            owner_email=None,
            team_id=None,
        )
        mock_template_resource.id = "template-public"
        mock_template_resource.uri = "docs://{page}"
        mock_template_resource.mime_type = "text/plain"
        mock_template_resource.content = "documentation"

        from mcpgateway.common.models import ResourceContent

        mock_content = ResourceContent(
            type="resource",
            id="template-public",
            uri="docs://{page}",
            mime_type="text/plain",
            text="documentation",
        )

        call_count = [0]

        def mock_execute(query):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # First call: lookup by URI - not found
                mock_result.scalar_one_or_none.return_value = None
            elif call_count[0] == 2:
                # Second call: inactivity check - not inactive
                mock_result.scalar_one_or_none.return_value = None
            else:
                # Third+ calls: template lookup by ID
                mock_result.scalar_one_or_none.return_value = mock_template_resource
                mock_result.first.return_value = None
            return mock_result

        mock_db.execute = mock_execute

        with patch.object(resource_service, "_read_template_resource", new_callable=AsyncMock) as mock_read_template:
            mock_read_template.return_value = mock_content

            # Unauthenticated user with public-only token
            result = await resource_service.read_resource(
                mock_db,
                resource_uri="docs://intro",
                user=None,
                token_teams=[],  # Public-only
            )

            assert result is not None
