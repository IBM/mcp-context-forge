# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_authorization_access.py
Copyright 2026
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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceNotFoundError, ResourceService
from mcpgateway.services.tool_service import ToolNotFoundError, ToolService
from tests.helpers.admin_mocks import install_admin_user


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
    tool.created_by = None
    tool.created_from_ip = None
    tool.created_via = None
    tool.created_user_agent = None
    tool.modified_by = None
    tool.modified_from_ip = None
    tool.modified_via = None
    tool.modified_user_agent = None
    tool.import_batch_id = None
    tool.federation_source = None
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
    async def test_admin_bypass_denied_for_private_resources(self, tool_service, mock_db):
        """Admin bypass does NOT grant access to private resources (security requirement)."""
        tool_payload = {
            "id": "tool-123",
            "visibility": "private",
            "owner_email": "owner@example.com",
            "team_id": "team-abc",
        }

        # Admin bypass: both user_email and token_teams are None
        # Private resources are NEVER accessible via admin bypass
        result = await tool_service._check_tool_access(mock_db, tool_payload, user_email=None, token_teams=None)
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_bypass_grants_access_to_team_resources(self, tool_service, mock_db):
        """Admin bypass grants access to team and public resources, but not private."""
        # Test team visibility
        team_tool_payload = {
            "id": "tool-123",
            "visibility": "team",
            "owner_email": "owner@example.com",
            "team_id": "team-abc",
        }
        result = await tool_service._check_tool_access(mock_db, team_tool_payload, user_email=None, token_teams=None)
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
    async def test_admin_bypass_denied_for_private_resources(self, resource_service, mock_db):
        """Admin bypass does NOT grant access to private resources (security requirement)."""
        mock_resource = create_mock_resource(visibility="private", owner_email="owner@example.com", team_id="team-abc")

        # Private resources are NEVER accessible via admin bypass
        result = await resource_service._check_resource_access(mock_db, mock_resource, user_email=None, token_teams=None)
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_bypass_grants_access_to_team_resources(self, resource_service, mock_db):
        """Admin bypass grants access to team and public resources, but not private."""
        # Test team visibility
        mock_resource = create_mock_resource(visibility="team", owner_email="owner@example.com", team_id="team-abc")
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
    async def test_admin_bypass_denied_for_private_resources(self, prompt_service, mock_db):
        """Admin bypass does NOT grant access to private resources (security requirement)."""
        mock_prompt = create_mock_prompt(visibility="private", owner_email="owner@example.com", team_id="team-abc")

        # Private resources are NEVER accessible via admin bypass
        result = await prompt_service._check_prompt_access(mock_db, mock_prompt, user_email=None, token_teams=None)
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_bypass_grants_access_to_team_resources(self, prompt_service, mock_db):
        """Admin bypass grants access to team and public resources, but not private."""
        # Test team visibility
        mock_prompt = create_mock_prompt(visibility="team", owner_email="owner@example.com", team_id="team-abc")
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
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
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
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
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
    async def test_invoke_tool_admin_bypass_denied_for_private(self, tool_service, mock_db):
        """Admin bypass cannot execute private tools (security requirement)."""
        mock_tool = create_mock_tool(visibility="private", owner_email="secret@example.com", team_id="secret-team")

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
        mock_db.execute = Mock(return_value=mock_scalar)

        # Admin bypass: user_email=None and token_teams=None
        # Should raise ToolNotFoundError because private tools are not accessible via admin bypass
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(
                mock_db,
                "test_tool",
                {},
                user_email=None,
                token_teams=None,
            )

        assert "Tool not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_private_denial_runs_before_pre_invoke_hook(self, tool_service, mock_db):
        """PR #4341: visibility deny happens BEFORE the plugin hook chain executes.

        The check order matters because plugin hooks may have side effects (logging,
        metrics, billing) that would leak existence/usage information about private
        tools that the caller cannot see. The fix gates the hook chain behind the
        access check at tool_service.py:4452-4455 / 4814-4830.

        The production code resolves the manager via ``_get_plugin_manager(...)``
        and then dispatches via ``plugin_manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, ...)``.
        We patch both so a regression that calls the real hook chain is caught;
        an earlier version of this test mocked an unused attribute and passed
        vacuously regardless of hook ordering.
        """
        mock_tool = create_mock_tool(visibility="private", owner_email="secret@example.com", team_id="secret-team")

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
        mock_db.execute = Mock(return_value=mock_scalar)

        mock_plugin_manager = MagicMock()
        mock_plugin_manager.has_hooks_for = MagicMock(return_value=True)
        mock_plugin_manager.invoke_hook = AsyncMock(return_value=(MagicMock(continue_processing=True, modified_payload=None), None))

        with patch.object(tool_service, "_get_plugin_manager", new_callable=AsyncMock, return_value=mock_plugin_manager):
            with pytest.raises(ToolNotFoundError):
                await tool_service.invoke_tool(
                    mock_db,
                    "secret_tool",
                    {},
                    user_email=None,
                    token_teams=None,
                )

        mock_plugin_manager.invoke_hook.assert_not_called()

    @pytest.mark.asyncio
    async def test_invoke_tool_admin_bypass_works_for_team_tools(self, tool_service, mock_db):
        """Admin with unrestricted token can execute team-visible tools."""
        mock_tool = create_mock_tool(visibility="team", owner_email="owner@example.com", team_id="team-a")

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
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
        assert result.content[0].text is not None


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
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
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
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
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

    @pytest.mark.asyncio
    async def test_list_tools_cache_hash_includes_visibility(self, tool_service, mock_db):
        """Cache hash must include visibility so admin requests with different visibility filters get different cache keys."""
        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()
            mock_cache.hash_filters = Mock(return_value="test_hash")
            mock_get_cache.return_value = mock_cache

            mock_scalars = Mock()
            mock_scalars.all.return_value = []
            mock_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=mock_scalars)))

            # Admin request with visibility=team
            await tool_service.list_tools(mock_db, user_email=None, token_teams=None, visibility="team")

            # hash_filters must include visibility="team"
            mock_cache.hash_filters.assert_called_once()
            call_kwargs = mock_cache.hash_filters.call_args[1]
            assert call_kwargs["visibility"] == "team"

    @pytest.mark.asyncio
    async def test_list_tools_cache_hash_visibility_none_when_unset(self, tool_service, mock_db):
        """Cache hash must include visibility=None when no visibility filter is set."""
        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()
            mock_cache.hash_filters = Mock(return_value="test_hash")
            mock_get_cache.return_value = mock_cache

            mock_scalars = Mock()
            mock_scalars.all.return_value = []
            mock_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=mock_scalars)))

            # Admin request without visibility filter
            await tool_service.list_tools(mock_db, user_email=None, token_teams=None)

            # hash_filters must include visibility=None
            mock_cache.hash_filters.assert_called_once()
            call_kwargs = mock_cache.hash_filters.call_args[1]
            assert call_kwargs["visibility"] is None

    @pytest.mark.asyncio
    async def test_list_tools_different_visibility_produces_different_cache_keys(self, tool_service, mock_db):
        """Different visibility values must produce different cache keys to prevent stale results."""
        from mcpgateway.cache.registry_cache import RegistryCache

        real_cache = RegistryCache()

        hash_no_filter = real_cache.hash_filters(include_inactive=False, tags=None, gateway_id=None, limit=100, visibility=None)
        hash_public = real_cache.hash_filters(include_inactive=False, tags=None, gateway_id=None, limit=100, visibility="public")
        hash_team = real_cache.hash_filters(include_inactive=False, tags=None, gateway_id=None, limit=100, visibility="team")
        hash_private = real_cache.hash_filters(include_inactive=False, tags=None, gateway_id=None, limit=100, visibility="private")

        # All hashes must be distinct
        all_hashes = [hash_no_filter, hash_public, hash_team, hash_private]
        assert len(set(all_hashes)) == 4, f"Expected 4 distinct hashes, got {set(all_hashes)}"

    @pytest.mark.asyncio
    async def test_admin_visibility_filter_changes_cache_key(self, tool_service, mock_db):
        """Admin requests with vs. without visibility filter must use different cache keys."""
        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()
            # Use the real hash_filters to verify distinct keys
            from mcpgateway.cache.registry_cache import RegistryCache

            real_cache = RegistryCache()
            mock_cache.hash_filters = real_cache.hash_filters
            mock_get_cache.return_value = mock_cache

            mock_scalars = Mock()
            mock_scalars.all.return_value = []
            mock_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=mock_scalars)))

            # First call: admin, no visibility filter
            await tool_service.list_tools(mock_db, user_email=None, token_teams=None)
            first_hash = mock_cache.get.call_args_list[0][0][1]

            # Second call: admin, visibility=team
            await tool_service.list_tools(mock_db, user_email=None, token_teams=None, visibility="team")
            second_hash = mock_cache.get.call_args_list[1][0][1]

            # The two hashes must be different
            assert first_hash != second_hash, "Cache keys must differ when visibility filter changes"


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


class TestDirectGetAccessDenial:
    """Regression tests for PR #4341 follow-up — admin bypass cannot read private resources via direct-ID getters.

    These tests cover the service-level access checks added to:
    - ServerService.get_server
    - GatewayService.get_gateway
    - A2AAgentService.get_agent_by_name / get_agent_card
    - PromptService.get_prompt_details
    - ResourceService.get_resource_by_id
    - ToolService.get_tool (JWT-scoped token_teams, not DB-expanded)
    """

    @pytest.mark.asyncio
    async def test_server_admin_bypass_denies_private(self):
        """SECURITY: ServerService.get_server must deny admin bypass access to private servers."""
        # First-Party
        from mcpgateway.services.server_service import ServerNotFoundError, ServerService

        service = ServerService()
        db = MagicMock()
        private_server = MagicMock()
        private_server.id = "s1"
        private_server.visibility = "private"
        private_server.owner_email = "other@example.com"
        private_server.team_id = None
        private_server.enabled = True
        db.execute.return_value.scalar_one_or_none.return_value = private_server

        with pytest.raises(ServerNotFoundError):
            await service.get_server(db, "s1", user_email=None, token_teams=None)

    @pytest.mark.asyncio
    async def test_server_admin_bypass_allows_team(self):
        """ServerService.get_server allows admin bypass for team servers (only private is denied)."""
        # First-Party
        from mcpgateway.services.server_service import ServerService

        service = ServerService()
        service.convert_server_to_read = MagicMock(return_value="server_read")
        service._structured_logger = MagicMock()
        service._audit_trail = MagicMock()
        db = MagicMock()
        team_server = MagicMock()
        team_server.id = "s2"
        team_server.visibility = "team"
        team_server.owner_email = "other@example.com"
        team_server.team_id = "team-a"
        team_server.enabled = True
        team_server.tools = []
        team_server.resources = []
        team_server.prompts = []
        db.execute.return_value.scalar_one_or_none.return_value = team_server

        result = await service.get_server(db, "s2", user_email=None, token_teams=None)
        assert result == "server_read"

    @pytest.mark.asyncio
    async def test_gateway_admin_bypass_denies_private(self):
        """SECURITY: GatewayService.get_gateway must deny admin bypass access to private gateways."""
        # First-Party
        from mcpgateway.services.gateway_service import GatewayNotFoundError, GatewayService

        service = GatewayService()
        try:
            db = MagicMock()
            private_gateway = MagicMock()
            private_gateway.id = "g1"
            private_gateway.visibility = "private"
            private_gateway.owner_email = "other@example.com"
            private_gateway.team_id = None
            private_gateway.enabled = True
            db.execute.return_value.scalar_one_or_none.return_value = private_gateway

            with pytest.raises(GatewayNotFoundError):
                await service.get_gateway(db, "g1", user_email=None, token_teams=None)
        finally:
            await service._http_client.aclose()

    @pytest.mark.asyncio
    async def test_agent_by_name_admin_bypass_denies_private(self):
        """SECURITY: A2AAgentService.get_agent_by_name must deny admin bypass access to private agents."""
        # First-Party
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError, A2AAgentService

        service = A2AAgentService()
        db = MagicMock()
        private_agent = MagicMock()
        private_agent.visibility = "private"
        private_agent.owner_email = "other@example.com"
        private_agent.team_id = None
        db.execute.return_value.scalar_one_or_none.return_value = private_agent

        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent_by_name(db, "agent-x", user_email=None, token_teams=None)

    @pytest.mark.asyncio
    async def test_agent_card_admin_bypass_denies_private(self):
        """SECURITY: A2AAgentService._check_agent_access denies private on anonymous admin bypass.

        After PR #4341 cycle 2, ``get_agent_card`` itself awaits ``_check_agent_access``
        internally and returns ``None`` on deny, so the in-service gate is the
        canonical enforcement point. This test exercises that gate directly to
        keep the regression coverage focused: a service-layer change that broke
        the deny path would fail this assertion before any caller-side test.
        """
        # First-Party
        from mcpgateway.services.a2a_service import A2AAgentService

        service = A2AAgentService()
        db = MagicMock()
        private_agent = MagicMock()
        private_agent.name = "agent-x"
        private_agent.visibility = "private"
        private_agent.owner_email = "other@example.com"
        private_agent.team_id = None

        assert await service._check_agent_access(db, private_agent, user_email=None, token_teams=None) is False

    @pytest.mark.asyncio
    async def test_prompt_details_admin_bypass_denies_private(self, prompt_service, mock_db):
        """SECURITY: PromptService.get_prompt_details must deny admin bypass access to private prompts."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptNotFoundError

        private_prompt = create_mock_prompt(visibility="private", owner_email="other@example.com")
        mock_db.get.return_value = private_prompt

        with pytest.raises(PromptNotFoundError):
            await prompt_service.get_prompt_details(mock_db, "p1", user_email=None, token_teams=None)

    @pytest.mark.asyncio
    async def test_resource_by_id_admin_bypass_denies_private(self, resource_service, mock_db):
        """SECURITY: ResourceService.get_resource_by_id must deny admin bypass access to private resources."""
        private_resource = create_mock_resource(visibility="private", owner_email="other@example.com")
        private_resource.enabled = True
        mock_db.execute.return_value.scalar_one_or_none.return_value = private_resource

        with pytest.raises(ResourceNotFoundError):
            await resource_service.get_resource_by_id(mock_db, "r1", user_email=None, token_teams=None)

    @pytest.mark.asyncio
    async def test_tool_get_does_not_widen_scoped_token(self, tool_service, mock_db):
        """SECURITY: get_tool must honor scoped token_teams rather than expanding to full DB team roles.

        Regression for the B2 fix: previously get_tool fetched ``get_user_team_roles(db, email)``
        which returned the user's FULL team membership, bypassing a token scoped to a subset.
        After the fix, the endpoint passes JWT-scoped ``token_teams=[]`` through verbatim, so a
        team-B tool remains hidden from a public-only token even if the user belongs to team B.
        """
        team_tool = create_mock_tool(visibility="team", owner_email="owner@example.com", team_id="team-b")
        mock_db.get.return_value = team_tool

        with pytest.raises(ToolNotFoundError):
            await tool_service.get_tool(
                mock_db,
                "tool-123",
                requesting_user_email="owner@example.com",
                requesting_user_is_admin=False,
                requesting_user_team_roles={"team-b": "viewer"},  # DB-resolved; must NOT be used for visibility
                token_teams=[],  # JWT-scoped: public-only
            )

    @pytest.mark.asyncio
    async def test_tool_get_admin_bypass_sees_team_tool(self, tool_service, mock_db):
        """Admin bypass (token_teams=None) still grants access to team-visible tools via get_tool."""
        team_tool = create_mock_tool(visibility="team", owner_email="other@example.com", team_id="team-b")
        mock_db.get.return_value = team_tool
        tool_service.convert_tool_to_read = MagicMock(return_value=MagicMock())

        result = await tool_service.get_tool(
            mock_db,
            "tool-123",
            requesting_user_email=None,
            requesting_user_is_admin=True,
            requesting_user_team_roles=None,
            token_teams=None,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_access_denied_emits_structured_log_event(self, tool_service, mock_db):
        """PR #4341 forensics: denial path emits ``tool_access_denied`` event with the documented shape.

        The CHANGELOG promises that direct-ID denials emit ``*_access_denied`` events
        suitable for forensic review. Without this assertion, the event shape
        (event_type, resource_type, resource_id, team_id, user_email, custom_fields)
        could drift silently.
        """
        # First-Party
        import mcpgateway.services.tool_service as tool_service_mod

        private_tool = create_mock_tool(visibility="private", owner_email="other@example.com", team_id="team-other")
        mock_db.get.return_value = private_tool

        with patch.object(tool_service_mod, "structured_logger") as mock_logger:
            with pytest.raises(ToolNotFoundError):
                await tool_service.get_tool(
                    mock_db,
                    "tool-123",
                    requesting_user_email=None,
                    requesting_user_is_admin=True,
                    requesting_user_team_roles=None,
                    token_teams=None,
                )

            mock_logger.log.assert_called_once()
            call_kwargs = mock_logger.log.call_args.kwargs
            assert call_kwargs["event_type"] == "tool_access_denied"
            assert call_kwargs["resource_type"] == "tool"
            assert call_kwargs["resource_id"] == "tool-123"
            assert "visibility" in call_kwargs["custom_fields"]
            assert call_kwargs["custom_fields"]["visibility"] == "private"
            assert "admin_bypass" in call_kwargs["custom_fields"]

    @pytest.mark.asyncio
    async def test_list_resource_templates_admin_bypass_excludes_private(self, resource_service, mock_db):
        """SECURITY: list_resource_templates under admin bypass applies a private-exclusion WHERE clause."""
        captured_queries = []

        original_result = MagicMock()
        original_result.scalars.return_value.all.return_value = []

        def mock_execute(stmt):
            captured_queries.append(stmt)
            return original_result

        mock_db.execute = mock_execute

        await resource_service.list_resource_templates(
            mock_db,
            user_email=None,
            token_teams=None,
        )

        assert captured_queries, "expected a query to be executed"
        compiled = str(captured_queries[0].compile(compile_kwargs={"literal_binds": True}))
        assert "visibility" in compiled and "private" in compiled

    @pytest.mark.asyncio
    async def test_list_resource_templates_db_admin_includes_own_private_only(self, resource_service, mock_db):
        """PR #4341 carve-out: DB-admin (email, None) shape sees own private but not others'.

        Previously the bespoke admin-bypass branch in ``list_resource_templates``
        only handled ``(None, None)`` and let the ``(email, None)`` DB-admin
        shape fall through with no WHERE clause applied, leaking all private
        templates.

        Uses a non-platform-admin email and patches ``is_user_admin`` directly
        so the DB-resolved admin code path is exercised — not the
        ``settings.platform_admin_email`` shortcut, which would mask a regression
        that broke the DB-resolved branch but kept the platform-admin fast path.
        """
        captured_queries = []

        original_result = MagicMock()
        original_result.scalars.return_value.all.return_value = []

        def mock_execute(stmt):
            captured_queries.append(stmt)
            return original_result

        mock_db.execute = mock_execute

        with patch("mcpgateway.services.resource_service.is_user_admin", return_value=True):
            await resource_service.list_resource_templates(
                mock_db,
                user_email="dba@test.com",
                token_teams=None,
            )

        assert captured_queries, "expected a query to be executed"
        compiled = str(captured_queries[0].compile(compile_kwargs={"literal_binds": True}))

        assert "visibility != 'private'" in compiled, f"public/team carve-out missing: {compiled}"
        assert "visibility = 'private'" in compiled, f"own-private allowance missing: {compiled}"
        assert "owner_email = 'dba@test.com'" in compiled, f"owner clause must bind caller email: {compiled}"
        # The carve-out is exactly one OR — multiple ORs would indicate a wrong predicate
        # (e.g. unconditional private allowance bolted on).
        or_count = compiled.upper().count(" OR ")
        assert or_count == 1, f"expected exactly 1 OR in WHERE clause, got {or_count}: {compiled}"

    @pytest.mark.asyncio
    async def test_completion_apply_visibility_scope_admin_bypass_excludes_private(self):
        """SECURITY: completion_service._apply_visibility_scope under admin bypass compiles a visibility != 'private' WHERE clause.

        Hardened regression for PR #4341 follow-up: asserts the actual compiled predicate,
        not just that ``.where()`` was called, so a wrong predicate cannot slip through.
        """
        # Third-Party
        from sqlalchemy import select

        # First-Party
        from mcpgateway.db import Prompt as DbPrompt
        from mcpgateway.services.completion_service import CompletionService

        service = CompletionService()
        stmt = select(DbPrompt)

        scoped = service._apply_visibility_scope(stmt, DbPrompt, user_email=None, token_teams=None, team_ids=[], db=MagicMock())
        compiled = str(scoped.compile(compile_kwargs={"literal_binds": True}))

        assert "visibility" in compiled
        assert "private" in compiled
        assert "!=" in compiled or "<>" in compiled

    @pytest.mark.asyncio
    async def test_tag_apply_visibility_scope_admin_bypass_excludes_private(self):
        """SECURITY: tag_service._apply_visibility_scope under admin bypass compiles a visibility != 'private' WHERE clause.

        Hardened regression for PR #4341 follow-up: same reasoning as the completion
        test - a structurally wrong predicate must not pass as a true ``where`` call.
        """
        # Third-Party
        from sqlalchemy import select

        # First-Party
        from mcpgateway.db import Resource as DbResource
        from mcpgateway.services.tag_service import TagService

        service = TagService()
        stmt = select(DbResource)

        scoped = service._apply_visibility_scope(stmt, DbResource, user_email=None, token_teams=None, team_ids=[], db=MagicMock())
        compiled = str(scoped.compile(compile_kwargs={"literal_binds": True}))

        assert "visibility" in compiled
        assert "private" in compiled
        assert "!=" in compiled or "<>" in compiled


class TestServerAccessCheckMatrix:
    """Branch coverage for ServerService._check_server_access (server_service.py:1015-1044).

    Mirrors the existing TestCheckToolAccess matrix in test_tool_service.py so that
    every documented policy outcome (public allow, anonymous bypass deny private,
    public-only token deny, own-private allow, team membership via JWT, team
    membership via DB lookup, final deny) has at least one focused regression.
    """

    @pytest.fixture
    def service(self):
        from mcpgateway.services.server_service import ServerService

        return ServerService()

    @staticmethod
    def _server(visibility: str, owner_email=None, team_id=None) -> MagicMock:
        s = MagicMock()
        s.visibility = visibility
        s.owner_email = owner_email
        s.team_id = team_id
        return s

    @pytest.mark.asyncio
    async def test_public_always_allowed(self, service):
        """Public visibility short-circuits before any other check."""
        s = self._server("public")
        assert await service._check_server_access(MagicMock(), s, user_email=None, token_teams=[]) is True
        assert await service._check_server_access(MagicMock(), s, user_email="any@test.com", token_teams=["team-x"]) is True

    @pytest.mark.asyncio
    async def test_anonymous_admin_bypass_denies_private(self, service):
        """(None, None) anonymous admin bypass: team allowed, private denied."""
        assert await service._check_server_access(MagicMock(), self._server("private", owner_email="other@test.com"), user_email=None, token_teams=None) is False
        assert await service._check_server_access(MagicMock(), self._server("team", team_id="team-x"), user_email=None, token_teams=None) is True

    @pytest.mark.asyncio
    async def test_no_user_email_with_token_teams_denied(self, service):
        """(None, [team]) shape: server_service.py line 1022-1023 — without user_email, denied."""
        assert await service._check_server_access(MagicMock(), self._server("team", team_id="team-x"), user_email=None, token_teams=["team-x"]) is False

    @pytest.mark.asyncio
    async def test_public_only_token_denies_non_public(self, service):
        """(email, []) public-only token: covers server_service.py line 1025-1027."""
        s_team = self._server("team", team_id="team-x")
        s_private = self._server("private", owner_email="user@test.com")
        assert await service._check_server_access(MagicMock(), s_team, user_email="user@test.com", token_teams=[]) is False
        assert await service._check_server_access(MagicMock(), s_private, user_email="user@test.com", token_teams=[]) is False

    @pytest.mark.asyncio
    async def test_own_private_allowed(self, service):
        """Owner of a private server can read it (covers line 1029-1031)."""
        own = self._server("private", owner_email="user@test.com")
        assert await service._check_server_access(MagicMock(), own, user_email="user@test.com", token_teams=["team-x"]) is True

    @pytest.mark.asyncio
    async def test_team_member_via_jwt_token_teams(self, service):
        """token_teams from JWT carries team membership (covers line 1033-1036)."""
        s = self._server("team", team_id="team-x")
        assert await service._check_server_access(MagicMock(), s, user_email="user@test.com", token_teams=["team-x"]) is True
        # Non-matching team in JWT → denied (covers line 1044 fall-through).
        assert await service._check_server_access(MagicMock(), s, user_email="user@test.com", token_teams=["team-y"]) is False

    @pytest.mark.asyncio
    async def test_team_member_via_db_lookup(self, service):
        """token_teams=None with email + team server: falls back to TeamManagementService (covers line 1038-1042)."""
        s = self._server("team", team_id="team-x")

        with patch("mcpgateway.services.server_service.TeamManagementService") as mock_tms_cls:
            mock_tms_cls.return_value.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="team-x")])
            allowed = await service._check_server_access(MagicMock(), s, user_email="user@test.com", token_teams=None)

        assert allowed is True
        mock_tms_cls.return_value.get_user_teams.assert_awaited_once_with("user@test.com")


class TestGatewayAccessCheckMatrix:
    """Branch coverage for GatewayService._check_gateway_access (gateway_service.py:2732-2761).

    Same shape as TestServerAccessCheckMatrix above — both helpers were added by
    PR #4341 and both implement the canonical hybrid visibility policy.
    """

    @pytest.fixture
    def service(self):
        from mcpgateway.services.gateway_service import GatewayService

        return GatewayService()

    @staticmethod
    def _gw(visibility: str, owner_email=None, team_id=None) -> MagicMock:
        g = MagicMock()
        g.visibility = visibility
        g.owner_email = owner_email
        g.team_id = team_id
        return g

    @pytest.mark.asyncio
    async def test_public_always_allowed(self, service):
        """Covers gateway_service.py line 2734."""
        g = self._gw("public")
        assert await service._check_gateway_access(MagicMock(), g, user_email=None, token_teams=[]) is True

    @pytest.mark.asyncio
    async def test_anonymous_admin_bypass_denies_private(self, service):
        """(None, None) anonymous admin bypass: team allowed, private denied."""
        assert await service._check_gateway_access(MagicMock(), self._gw("private", owner_email="other@test.com"), user_email=None, token_teams=None) is False
        assert await service._check_gateway_access(MagicMock(), self._gw("team", team_id="team-x"), user_email=None, token_teams=None) is True

    @pytest.mark.asyncio
    async def test_no_user_email_with_token_teams_denied(self, service):
        """(None, [team]) shape: covers gateway_service.py line 2739-2740."""
        assert await service._check_gateway_access(MagicMock(), self._gw("team", team_id="team-x"), user_email=None, token_teams=["team-x"]) is False

    @pytest.mark.asyncio
    async def test_public_only_token_denies_non_public(self, service):
        """(email, []) public-only token: covers line 2742-2744."""
        g_team = self._gw("team", team_id="team-x")
        g_private = self._gw("private", owner_email="user@test.com")
        assert await service._check_gateway_access(MagicMock(), g_team, user_email="user@test.com", token_teams=[]) is False
        assert await service._check_gateway_access(MagicMock(), g_private, user_email="user@test.com", token_teams=[]) is False

    @pytest.mark.asyncio
    async def test_own_private_allowed(self, service):
        """Owner of a private gateway can read it (covers line 2746-2748)."""
        own = self._gw("private", owner_email="user@test.com")
        assert await service._check_gateway_access(MagicMock(), own, user_email="user@test.com", token_teams=["team-x"]) is True

    @pytest.mark.asyncio
    async def test_team_member_via_jwt_token_teams(self, service):
        """token_teams from JWT carries team membership (covers line 2750-2753)."""
        g = self._gw("team", team_id="team-x")
        assert await service._check_gateway_access(MagicMock(), g, user_email="user@test.com", token_teams=["team-x"]) is True
        # Non-matching team in JWT → denied (covers line 2761 fall-through).
        assert await service._check_gateway_access(MagicMock(), g, user_email="user@test.com", token_teams=["team-y"]) is False

    @pytest.mark.asyncio
    async def test_team_member_via_db_lookup(self, service):
        """token_teams=None with email + team gateway: falls back to TeamManagementService (covers line 2755-2759)."""
        g = self._gw("team", team_id="team-x")

        with patch("mcpgateway.services.gateway_service.TeamManagementService") as mock_tms_cls:
            mock_tms_cls.return_value.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="team-x")])
            allowed = await service._check_gateway_access(MagicMock(), g, user_email="user@test.com", token_teams=None)

        assert allowed is True
        mock_tms_cls.return_value.get_user_teams.assert_awaited_once_with("user@test.com")
