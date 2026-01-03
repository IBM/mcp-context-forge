# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_resource_ownership.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for resource ownership checks in RBAC system.
Tests ensure only resource owners can delete/edit their resources.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway, Server, Tool, Resource, Prompt, A2AAgent
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.gateway_service.audit_trail") as mock_gw_audit, \
         patch("mcpgateway.services.gateway_service.structured_logger") as mock_gw_logger, \
         patch("mcpgateway.services.tool_service.audit_trail") as mock_tool_audit, \
         patch("mcpgateway.services.tool_service.structured_logger") as mock_tool_logger, \
         patch("mcpgateway.services.resource_service.audit_trail") as mock_res_audit, \
         patch("mcpgateway.services.resource_service.structured_logger") as mock_res_logger, \
         patch("mcpgateway.services.prompt_service.audit_trail") as mock_prompt_audit, \
         patch("mcpgateway.services.prompt_service.structured_logger") as mock_prompt_logger, \
         patch("mcpgateway.services.a2a_service.structured_logger") as mock_a2a_logger:
        for mock in [mock_gw_audit, mock_tool_audit, mock_res_audit, mock_prompt_audit]:
            mock.log_action = MagicMock(return_value=None)
        for mock in [mock_gw_logger, mock_tool_logger, mock_res_logger, mock_prompt_logger, mock_a2a_logger]:
            mock.log = MagicMock(return_value=None)
            mock.info = MagicMock(return_value=None)
        yield


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def permission_service(mock_db_session):
    """Create permission service instance."""
    return PermissionService(mock_db_session)


class TestCheckResourceOwnership:
    """Test check_resource_ownership method in PermissionService."""

    @pytest.mark.asyncio
    async def test_owner_can_access_resource(self, permission_service):
        """Test that resource owner is granted access."""
        # Create mock resource with owner_email
        mock_resource = MagicMock()
        mock_resource.owner_email = "owner@example.com"
        mock_resource.team_id = None
        mock_resource.visibility = "private"

        # Mock _is_user_admin to return False
        permission_service._is_user_admin = AsyncMock(return_value=False)

        result = await permission_service.check_resource_ownership("owner@example.com", mock_resource)

        assert result == True

    @pytest.mark.asyncio
    async def test_non_owner_denied_access(self, permission_service):
        """Test that non-owner is denied access to private resource."""
        mock_resource = MagicMock()
        mock_resource.owner_email = "owner@example.com"
        mock_resource.team_id = None
        mock_resource.visibility = "private"

        # Mock _is_user_admin to return False
        permission_service._is_user_admin = AsyncMock(return_value=False)

        result = await permission_service.check_resource_ownership("other@example.com", mock_resource)

        assert result == False

    @pytest.mark.asyncio
    async def test_team_admin_can_access_team_resource(self, permission_service):
        """Test that team admin can access team-scoped resource."""
        mock_resource = MagicMock()
        mock_resource.owner_email = "member@example.com"
        mock_resource.team_id = "team-123"
        mock_resource.visibility = "team"

        # Mock _is_user_admin and _get_user_team_role
        permission_service._is_user_admin = AsyncMock(return_value=False)
        permission_service._get_user_team_role = AsyncMock(return_value="owner")

        result = await permission_service.check_resource_ownership("admin@example.com", mock_resource)

        assert result == True

    @pytest.mark.asyncio
    async def test_team_member_cannot_edit_team_resource(self, permission_service):
        """Test that regular team member cannot edit another member's resource."""
        mock_resource = MagicMock()
        mock_resource.owner_email = "member1@example.com"
        mock_resource.team_id = "team-123"
        mock_resource.visibility = "team"

        # Mock _is_user_admin and _get_user_team_role
        permission_service._is_user_admin = AsyncMock(return_value=False)
        permission_service._get_user_team_role = AsyncMock(return_value="member")

        result = await permission_service.check_resource_ownership("member2@example.com", mock_resource)

        assert result == False

    @pytest.mark.asyncio
    async def test_public_resource_non_owner_denied_edit(self, permission_service):
        """Test that non-owner cannot edit public resource despite visibility."""
        mock_resource = MagicMock()
        mock_resource.owner_email = "owner@example.com"
        mock_resource.team_id = None
        mock_resource.visibility = "public"

        # Mock _is_user_admin to return False
        permission_service._is_user_admin = AsyncMock(return_value=False)

        result = await permission_service.check_resource_ownership("other@example.com", mock_resource)

        assert result == False


class TestGatewayServiceOwnership:
    """Test ownership checks in GatewayService delete/update methods."""

    @pytest.fixture
    def gateway_service(self):
        """Create gateway service instance."""
        return GatewayService()

    @pytest.mark.asyncio
    async def test_delete_gateway_owner_success(self, gateway_service, mock_db_session):
        """Test owner can delete their gateway."""
        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gateway-1"
        mock_gateway.owner_email = "owner@example.com"
        mock_gateway.name = "Test Gateway"
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        # Gateway service uses db.execute(select().options().where()) for eager loading
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_gateway
        mock_db_session.execute.return_value = mock_execute_result

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=True)

            await gateway_service.delete_gateway(mock_db_session, "gateway-1", user_email="owner@example.com")

            mock_db_session.delete.assert_called_once_with(mock_gateway)
            mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_gateway_non_owner_denied(self, gateway_service, mock_db_session):
        """Test non-owner cannot delete gateway."""
        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gateway-1"
        mock_gateway.owner_email = "owner@example.com"
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        # Gateway service uses db.execute(select().options().where()) for eager loading
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_gateway
        mock_db_session.execute.return_value = mock_execute_result

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=False)

            with pytest.raises(PermissionError, match="Only the owner can delete this gateway"):
                await gateway_service.delete_gateway(mock_db_session, "gateway-1", user_email="other@example.com")

            mock_db_session.delete.assert_not_called()


class TestServerServiceOwnership:
    """Test ownership checks in ServerService delete/update methods."""

    @pytest.fixture
    def server_service(self):
        """Create server service instance."""
        return ServerService()

    @pytest.mark.asyncio
    async def test_delete_server_owner_success(self, server_service, mock_db_session):
        """Test owner can delete their server."""
        mock_server = MagicMock(spec=Server)
        mock_server.id = "server-1"
        mock_server.owner_email = "owner@example.com"
        mock_server.name = "Test Server"

        mock_db_session.get.return_value = mock_server

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=True)

            await server_service.delete_server(mock_db_session, "server-1", user_email="owner@example.com")

            mock_db_session.delete.assert_called_once_with(mock_server)
            mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_server_non_owner_denied(self, server_service, mock_db_session):
        """Test non-owner cannot delete server."""
        mock_server = MagicMock(spec=Server)
        mock_server.id = "server-1"
        mock_server.owner_email = "owner@example.com"

        mock_db_session.get.return_value = mock_server

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=False)

            with pytest.raises(PermissionError, match="Only the owner can delete this server"):
                await server_service.delete_server(mock_db_session, "server-1", user_email="other@example.com")

            mock_db_session.delete.assert_not_called()


class TestToolServiceOwnership:
    """Test ownership checks in ToolService delete/update methods."""

    @pytest.fixture
    def tool_service(self):
        """Create tool service instance."""
        return ToolService()

    @pytest.mark.asyncio
    async def test_delete_tool_owner_success(self, tool_service, mock_db_session):
        """Test owner can delete their tool."""
        mock_tool = MagicMock(spec=Tool)
        mock_tool.id = "tool-1"
        mock_tool.owner_email = "owner@example.com"
        mock_tool.name = "Test Tool"

        mock_db_session.get.return_value = mock_tool

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=True)

            await tool_service.delete_tool(mock_db_session, "tool-1", user_email="owner@example.com")

            mock_db_session.delete.assert_called_once_with(mock_tool)
            mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_tool_non_owner_denied(self, tool_service, mock_db_session):
        """Test non-owner cannot delete tool."""
        mock_tool = MagicMock(spec=Tool)
        mock_tool.id = "tool-1"
        mock_tool.owner_email = "owner@example.com"

        mock_db_session.get.return_value = mock_tool

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=False)

            with pytest.raises(PermissionError, match="Only the owner can delete this tool"):
                await tool_service.delete_tool(mock_db_session, "tool-1", user_email="other@example.com")

            mock_db_session.delete.assert_not_called()


class TestResourcePromptA2AOwnership:
    """Test ownership checks in Resource, Prompt, and A2A services."""

    @pytest.fixture
    def resource_service(self):
        """Create resource service instance."""
        return ResourceService()

    @pytest.fixture
    def prompt_service(self):
        """Create prompt service instance."""
        return PromptService()

    @pytest.fixture
    def a2a_service(self):
        """Create A2A service instance."""
        return A2AAgentService()

    @pytest.mark.asyncio
    async def test_delete_resource_non_owner_denied(self, resource_service, mock_db_session):
        """Test non-owner cannot delete resource."""
        mock_resource = MagicMock(spec=Resource)
        mock_resource.uri = "test://resource"
        mock_resource.owner_email = "owner@example.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_resource
        mock_db_session.execute.return_value = mock_result

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=False)

            with pytest.raises(PermissionError, match="Only the owner can delete this resource"):
                await resource_service.delete_resource(mock_db_session, "test://resource", user_email="other@example.com")

    @pytest.mark.asyncio
    async def test_delete_prompt_non_owner_denied(self, prompt_service, mock_db_session):
        """Test non-owner cannot delete prompt."""
        mock_prompt = MagicMock(spec=Prompt)
        mock_prompt.name = "test-prompt"
        mock_prompt.owner_email = "owner@example.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_prompt
        mock_db_session.execute.return_value = mock_result

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=False)

            with pytest.raises(PermissionError, match="Only the owner can delete this prompt"):
                await prompt_service.delete_prompt(mock_db_session, "test-prompt", user_email="other@example.com")

    @pytest.mark.asyncio
    async def test_delete_a2a_agent_non_owner_denied(self, a2a_service, mock_db_session):
        """Test non-owner cannot delete A2A agent."""
        mock_agent = MagicMock(spec=A2AAgent)
        mock_agent.id = "agent-1"
        mock_agent.owner_email = "owner@example.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db_session.execute.return_value = mock_result

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=False)

            with pytest.raises(PermissionError, match="Only the owner can delete this agent"):
                await a2a_service.delete_agent(mock_db_session, "agent-1", user_email="other@example.com")


class TestUpdateOperationsOwnership:
    """Test ownership checks in update operations."""

    @pytest.fixture
    def gateway_service(self):
        """Create gateway service instance."""
        return GatewayService()

    @pytest.mark.asyncio
    async def test_update_gateway_non_owner_denied(self, gateway_service, mock_db_session):
        """Test non-owner cannot update gateway."""
        from mcpgateway.schemas import GatewayUpdate

        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gateway-1"
        mock_gateway.owner_email = "owner@example.com"
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        # Gateway service uses db.execute(select().options().where()) for eager loading
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_gateway
        mock_db_session.execute.return_value = mock_execute_result

        gateway_update = GatewayUpdate(name="Updated Name")

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=False)

            with pytest.raises(PermissionError, match="Only the owner can update this gateway"):
                await gateway_service.update_gateway(mock_db_session, "gateway-1", gateway_update, user_email="other@example.com")


class TestTeamAdminSpecialCase:
    """Test team admin can delete team members' resources."""

    @pytest.fixture
    def gateway_service(self):
        """Create gateway service instance."""
        return GatewayService()

    @pytest.mark.asyncio
    async def test_team_admin_can_delete_team_resource(self, gateway_service, mock_db_session):
        """Test team admin can delete team member's resource."""
        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gateway-1"
        mock_gateway.owner_email = "member@example.com"
        mock_gateway.team_id = "team-123"
        mock_gateway.name = "Team Gateway"
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        # Gateway service uses db.execute(select().options().where()) for eager loading
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_gateway
        mock_db_session.execute.return_value = mock_execute_result

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            # Team admin returns True for ownership check
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=True)

            await gateway_service.delete_gateway(mock_db_session, "gateway-1", user_email="admin@example.com")

            mock_db_session.delete.assert_called_once_with(mock_gateway)
            mock_db_session.commit.assert_called_once()
