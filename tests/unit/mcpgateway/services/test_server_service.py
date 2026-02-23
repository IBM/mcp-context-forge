# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for server service implementation.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ServerCreate, ServerRead, ServerUpdate
from mcpgateway.services.server_service import (
    ServerError,
    ServerNotFoundError,
    ServerService,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def server_service() -> ServerService:
    """Return a fresh ServerService instance for every test."""
    return ServerService()


@pytest.fixture
def mock_tool():
    tool = MagicMock(spec=DbTool)
    tool.id = "101"
    tool.name = "test_tool"
    tool.created_by = "test_user"
    tool.modified_by = "test_user"
    tool._sa_instance_state = MagicMock()  # Mock the SQLAlchemy instance state
    return tool


@pytest.fixture
def mock_resource():
    res = MagicMock(spec=DbResource)
    res.id = "201"
    res.name = "test_resource"
    res.created_by = "test_user"
    res.modified_by = "test_user"
    res._sa_instance_state = MagicMock()  # Mock the SQLAlchemy instance state
    return res


@pytest.fixture
def mock_prompt():
    pr = MagicMock(spec=DbPrompt)
    pr.id = "301"
    pr.name = "test_prompt"
    pr.created_by = "test_user"
    pr.modified_by = "test_user"
    pr._sa_instance_state = MagicMock()  # Mock the SQLAlchemy instance state
    return pr


@pytest.fixture
def mock_server(mock_tool, mock_resource, mock_prompt):
    """Return a mocked DbServer object with minimal required attributes."""
    server = MagicMock(spec=DbServer)
    server.id = "1"
    server.name = "test_server"
    server.description = "A test server"
    server.icon = "server-icon"
    server.created_by = "test_user"
    server.modified_by = "test_user"
    server.created_at = "2023-01-01T00:00:00"
    server.updated_at = "2023-01-01T00:00:00"
    server.enabled = True

    # Ownership fields for RBAC
    server.owner_email = "user@example.com"  # Match default test user
    server.team_id = None
    server.team = None  # Team name loaded via email_team relationship
    server.visibility = "public"

    # Optional tracking fields (must be explicitly set to avoid MagicMock auto-creation)
    server.created_from_ip = None
    server.created_via = None
    server.created_user_agent = None
    server.modified_from_ip = None
    server.modified_via = None
    server.modified_user_agent = None
    server.import_batch_id = None
    server.federation_source = None
    server.version = 1

    # OAuth 2.0 configuration for RFC 9728 Protected Resource Metadata
    server.oauth_enabled = False
    server.oauth_config = None

    # Associated objects -------------------------------------------------- #
    server.tools = [mock_tool]
    server.resources = [mock_resource]
    server.prompts = [mock_prompt]
    server.a2a_agents = []

    # Dummy metrics
    server.metrics = []
    return server


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
class TestServerService:
    @pytest.mark.asyncio
    async def test_update_server_visibility_team_user_not_in_team(self, server_service, mock_server, test_db):
        """
        User not in team: should raise ValueError when changing visibility to 'team'.
        """
        # Setup: server has no team_id, update provides team_id
        mock_server.team_id = None
        test_db.get = Mock(return_value=mock_server)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Ensure get_for_update (which uses db.execute when loader options
        # are present) returns our mocked server instance.
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))
        test_db.rollback = Mock()

        # Mock team exists
        mock_team = MagicMock()

        # Mock no membership (user not in team)
        def query_side_effect(model):
            mock_query = MagicMock()
            if model.__name__ == "EmailTeam":
                # Team query returns a team (team exists)
                mock_query.filter.return_value.first.return_value = mock_team
            elif model.__name__ == "EmailTeamMember":
                # Member query returns None (user not a member/owner)
                mock_query.filter.return_value.first.return_value = None
            else:
                mock_query.filter.return_value.first.return_value = None
            return mock_query

        test_db.query = Mock(side_effect=query_side_effect)

        server_update = ServerUpdate(visibility="team", team_id="team1")
        test_user_email = "user@example.com"
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)):
            with pytest.raises(ServerError) as exc:
                await server_service.update_server(test_db, 1, server_update, test_user_email)
        assert "User membership in team not sufficient" in str(exc.value)

    @pytest.mark.asyncio
    async def test_update_server_visibility_team_user_not_owner(self, server_service, mock_server, test_db):
        """
        User is member but not owner: should raise ValueError when changing visibility to 'team'.
        """
        mock_server.team_id = "team1"
        test_db.get = Mock(return_value=mock_server)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Ensure get_for_update (which uses db.execute when loader options
        # are present) returns our mocked server instance.
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))
        test_db.rollback = Mock()
        # Patch db.query(DbEmailTeam).filter().first() to return a team
        mock_team = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_team
        test_db.query = Mock(return_value=mock_query)
        # Patch db.query(DbEmailTeamMember).filter().first() to return a member with role != 'owner'
        mock_member = MagicMock()
        mock_member.role = "member"
        member_query = MagicMock()
        member_query.filter.return_value.first.return_value = None  # The filter for role=="owner" returns None

        def query_side_effect(model):
            if model.__name__ == "EmailTeam":
                return mock_query
            elif model.__name__ == "EmailTeamMember":
                # Patch .filter(*args, **kwargs).first() to always return None
                member_query.filter = Mock()
                member_query.filter.return_value.first = Mock(return_value=None)
                return member_query
            return MagicMock()

        test_db.query.side_effect = query_side_effect
        server_update = ServerUpdate(visibility="team")
        test_user_email = "user@example.com"
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)):
            with pytest.raises(ServerError) as exc:
                await server_service.update_server(test_db, 1, server_update, test_user_email)
        assert "User membership in team not sufficient" in str(exc.value)

    @pytest.mark.asyncio
    async def test_update_server_visibility_team_user_is_owner(self, server_service, mock_server, test_db):
        """
        User is owner: should allow changing visibility to 'team'.
        """
        mock_server.team_id = "team1"
        test_db.get = Mock(return_value=mock_server)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Ensure get_for_update (which uses db.execute when loader options
        # are present) returns our mocked server instance.
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))
        # Patch db.query(DbEmailTeam).filter().first() to return a team
        mock_team = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_team
        test_db.query = Mock(return_value=mock_query)
        # Patch db.query(DbEmailTeamMember).filter().first() to return a member with role == 'owner'
        mock_member = MagicMock()
        mock_member.role = "owner"
        member_query = MagicMock()
        member_query.filter.return_value.first.return_value = mock_member

        def query_side_effect(model):
            if model.__name__ == "EmailTeam":
                return mock_query
            elif model.__name__ == "EmailTeamMember":
                return member_query
            return MagicMock()

        test_db.query.side_effect = query_side_effect
        server_service._notify_server_updated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="updated_server",
                description="An updated server",
                icon="http://example.com/image.jpg",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )
        server_update = ServerUpdate(visibility="team")
        test_user_email = "user@example.com"
        # Patch permission check to avoid DB user lookup in PermissionService
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)):
            result = await server_service.update_server(test_db, 1, server_update, test_user_email)
        assert result.name == "updated_server"

    """Unit-tests for the ServerService class."""

    # ------------------------- register_server -------------------------- #
    @pytest.mark.asyncio
    async def test_register_server(self, server_service, test_db, mock_tool, mock_resource, mock_prompt):
        """
        Successful registration returns a populated ServerRead.
        We mock the DB operations to avoid SQLAlchemy state issues.
        """
        # Pretend there is no existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock the created server instance
        mock_db_server = MagicMock(spec=DbServer)
        mock_db_server.id = "1"
        mock_db_server.name = "test_server"
        mock_db_server.description = "A test server"
        mock_db_server.icon = "http://example.com/image.jpg"
        mock_db_server.created_by = "test_user"
        mock_db_server.modified_by = "test_user"
        mock_db_server.created_at = "2023-01-01T00:00:00"
        mock_db_server.updated_at = "2023-01-01T00:00:00"
        mock_db_server.enabled = True
        mock_db_server.metrics = []

        # Create mock lists with append methods
        mock_tools = MagicMock()
        mock_resources = MagicMock()
        mock_prompts = MagicMock()

        # Track what gets appended
        appended_tools = []
        appended_resources = []
        appended_prompts = []

        mock_tools.append = Mock(side_effect=lambda x: appended_tools.append(x))
        mock_resources.append = Mock(side_effect=lambda x: appended_resources.append(x))
        mock_prompts.append = Mock(side_effect=lambda x: appended_prompts.append(x))

        # Make the lists iterable for the conversion
        mock_tools.__iter__ = Mock(return_value=iter(appended_tools))
        mock_resources.__iter__ = Mock(return_value=iter(appended_resources))
        mock_prompts.__iter__ = Mock(return_value=iter(appended_prompts))

        mock_db_server.tools = mock_tools
        mock_db_server.resources = mock_resources
        mock_db_server.prompts = mock_prompts

        # Mock db.add to capture the server being added
        added_server = None

        def capture_add(server):
            nonlocal added_server
            added_server = server
            # Standard
            from datetime import datetime, timezone

            # Set up the mock server to be returned later
            server.id = "1"  # Must be string, not int
            server.created_at = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            server.updated_at = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            server.tools = mock_tools
            server.resources = mock_resources
            server.prompts = mock_prompts
            server.metrics = []

        test_db.add = Mock(side_effect=capture_add)
        test_db.commit = Mock()
        test_db.refresh = Mock(side_effect=lambda x: None)  # Just pass through

        # Resolve associated objects
        test_db.get = Mock(
            side_effect=lambda cls, _id: {
                (DbTool, "101"): mock_tool,
                (DbResource, "201"): mock_resource,
                (DbPrompt, "301"): mock_prompt,
            }.get((cls, _id))
        )

        # Standard
        from datetime import datetime, timezone

        # Stub helper that converts to the public schema
        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at=datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                updated_at=datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                enabled=True,
                associated_tools=["101"],
                associated_resources=["201"],
                associated_prompts=["301"],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(
            name="test_server",
            description="A test server",
            icon="http://example.com/image.jpg",
            associated_tools=["101"],
            associated_resources=["201"],
            associated_prompts=["301"],
        )

        # Run
        result = await server_service.register_server(test_db, server_create)

        # Assertions
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        server_service._notify_server_added.assert_called_once()

        assert result.name == "test_server"
        assert "101" in result.associated_tools
        assert "201" in result.associated_resources
        assert "301" in result.associated_prompts

    @pytest.mark.asyncio
    async def test_register_server_name_conflict(self, server_service, mock_server, test_db):
        """Server name clash is surfaced as ServerError (wrapped by service)."""
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_server
        test_db.execute = Mock(return_value=mock_scalar)

        server_create = ServerCreate(
            name="test_server",
            description="A new server",
            icon="http://image.com/test.jpg",
        )

        with pytest.raises(ServerError) as exc:
            await server_service.register_server(test_db, server_create)

        # Accept either direct or wrapped error message
        msg = str(exc.value)
        assert "Server already exists with name" in msg or "Failed to register server" in msg

    @pytest.mark.asyncio
    async def test_register_server_invalid_associated_tool(self, server_service, test_db):
        """
        Non-existent associated tool raises ServerError.
        We let the real exception flow through without patching DbServer.
        """
        # No existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock db.add to not actually add anything
        test_db.add = Mock()

        # Simulate lookup failure for tool id 999
        test_db.get = Mock(return_value=None)
        test_db.rollback = Mock()

        server_create = ServerCreate(
            name="test_server",
            description="A test server",
            associated_tools=["999"],
        )

        with pytest.raises(ServerError) as exc:
            await server_service.register_server(test_db, server_create)

        assert "Tool with id 999 does not exist" in str(exc.value)
        test_db.rollback.assert_called_once()

    # --------------------------- list & get ----------------------------- #
    @pytest.mark.asyncio
    async def test_list_servers(self, server_service, mock_server, test_db):
        """list_servers returns converted models."""
        exec_result = MagicMock()
        mock_server.team_id = 1
        exec_result.scalars.return_value.all.return_value = [mock_server]
        test_db.execute = MagicMock(return_value=exec_result)

        server_read = ServerRead(
            id="1",
            name="test_server",
            description="A test server",
            icon="http://example.com/image.jgp",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            associated_tools=["101"],
            associated_resources=["201"],
            associated_prompts=["301"],
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
        )
        server_service.convert_server_to_read = Mock(return_value=server_read)

        result = await server_service.list_servers(test_db)

        # test_db.execute.assert_called_once()
        test_db.execute.call_count = 2
        servers, cursor = result
        assert servers == [server_read]
        assert cursor is None
        server_service.convert_server_to_read.assert_called_once_with(mock_server, include_metrics=False)

    @pytest.mark.asyncio
    async def test_list_servers_for_user_includes_team_name(self, server_service, test_db):
        """Test that list_servers_for_user properly populates team name via email_team relationship.

        This test guards against regressions if the joinedload strategy is changed.
        """
        # Mock a server with an active team relationship
        mock_email_team = Mock()
        mock_email_team.name = "Engineering Team"
        mock_server = Mock(
            enabled=True,
            team_id="team-123",
            email_team=mock_email_team,
            tools=[],
            resources=[],
            prompts=[],
            a2a_agents=[],
            metrics=[],
            visibility="public",
            owner_email="user@example.com",
        )
        # The team property should return the team name from email_team
        mock_server.team = mock_email_team.name

        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_server]
        test_db.execute = MagicMock(return_value=exec_result)

        # Use a mock that captures the server's team value
        captured_servers = []

        def capture_server(server, include_metrics=False):
            captured_servers.append({"team": server.team, "team_id": server.team_id})
            return "converted_server"

        server_service.convert_server_to_read = Mock(side_effect=capture_server)

        # Mock team service to return user's teams
        with patch("mcpgateway.services.server_service.TeamManagementService") as mock_team_service_class:
            mock_team_service = MagicMock()
            mock_team_service.get_user_teams = AsyncMock(return_value=[])
            mock_team_service_class.return_value = mock_team_service

            servers = await server_service.list_servers_for_user(test_db, "user@example.com")

        assert servers == ["converted_server"]
        # Verify the server's team was accessible during conversion
        assert len(captured_servers) == 1
        assert captured_servers[0]["team"] == "Engineering Team"
        assert captured_servers[0]["team_id"] == "team-123"

    @pytest.mark.asyncio
    async def test_get_server(self, server_service, mock_server, test_db):
        mock_server.team_id = 1
        test_db.get = MagicMock(return_value=mock_server)
        # Ensure get_for_update (which may use db.execute when loader options
        # are present) returns our mocked server instance.
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))

        server_read = ServerRead(
            id="1",
            name="test_server",
            description="A test server",
            icon="http://example.com/image.jpg",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            associated_tools=["101"],
            associated_resources=["201"],
            associated_prompts=["301"],
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
        )
        server_service.convert_server_to_read = Mock(return_value=server_read)

        result = await server_service.get_server(test_db, 1)

        # Depending on db backend implementation, get_for_update may call
        # `db.get(..., options=...)` or execute a select; assert at least one
        # of those was used and the result is as expected.
        assert result == server_read
        assert test_db.get.called or test_db.execute.called
        assert result == server_read

    @pytest.mark.asyncio
    async def test_get_server_not_found(self, server_service, test_db):
        test_db.get = Mock(return_value=None)
        with pytest.raises(ServerNotFoundError):
            await server_service.get_server(test_db, 999)

    # --------------------------- update -------------------------------- #
    @pytest.mark.asyncio
    async def test_update_server(self, server_service, mock_server, test_db, mock_tool, mock_resource, mock_prompt):
        # Mock new associated items
        new_tool = MagicMock(spec=DbTool)
        new_tool.id = 102
        new_tool.name = "new_tool"
        new_tool._sa_instance_state = MagicMock()

        new_resource = MagicMock(spec=DbResource)
        new_resource.id = 202
        new_resource.name = "new_resource"
        new_resource._sa_instance_state = MagicMock()

        new_prompt = MagicMock(spec=DbPrompt)
        new_prompt.id = 302
        new_prompt.name = "new_prompt"
        new_prompt._sa_instance_state = MagicMock()

        # db.get is still used to retrieve the Server itself (now with eager loading options)
        test_db.get = Mock(side_effect=lambda cls, _id, options=None: (mock_server if (cls, _id) == (DbServer, 1) else None))

        # Configure db.execute to handle the sequence of calls made by
        # `update_server`: 1) get_for_update (returns server),
        # 2) name conflict check (None), 3-5) bulk fetches for tools/resources/prompts.
        mock_result_get_server = Mock(scalar_one_or_none=Mock(return_value=mock_server))
        mock_result_name_conflict = Mock(scalar_one_or_none=Mock(return_value=None))

        mock_result_tools = Mock()
        mock_result_tools.scalars.return_value.all.return_value = [new_tool]

        mock_result_resources = Mock()
        mock_result_resources.scalars.return_value.all.return_value = [new_resource]

        mock_result_prompts = Mock()
        mock_result_prompts.scalars.return_value.all.return_value = [new_prompt]

        test_db.execute = Mock(
            side_effect=[
                mock_result_get_server,
                mock_result_name_conflict,
                mock_result_tools,
                mock_result_resources,
                mock_result_prompts,
            ]
        )

        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up mock server to track changes with mock lists
        mock_tools = MagicMock()
        mock_resources = MagicMock()
        mock_prompts = MagicMock()

        # These will hold the actual items
        tool_items = []
        resource_items = []
        prompt_items = []

        # Configure the mock lists to act like real lists for validation
        mock_tools.__iter__ = Mock(return_value=iter(tool_items))
        mock_resources.__iter__ = Mock(return_value=iter(resource_items))
        mock_prompts.__iter__ = Mock(return_value=iter(prompt_items))

        # Capture assignment to the lists (since the new code does server.tools = list(...))
        mock_server.tools = tool_items
        mock_server.resources = resource_items
        mock_server.prompts = prompt_items

        server_service._notify_server_updated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="updated_server",
                description="An updated server",
                icon="http://example.com/image.jpg",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=["102"],
                associated_resources=["202"],
                associated_prompts=["302"],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_update = ServerUpdate(
            name="updated_server",
            description="An updated server",
            icon="http://example.com/image.jpg",
            associated_tools=["102"],
            associated_resources=["202"],
            associated_prompts=["302"],
        )

        test_user_email = "user@example.com"

        # Patch permission check to avoid consuming db.execute side-effects
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)):
            result = await server_service.update_server(test_db, 1, server_update, test_user_email)

        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        server_service._notify_server_updated.assert_called_once()
        assert result.name == "updated_server"

    @pytest.mark.asyncio
    async def test_update_server_not_found(self, server_service, test_db):
        test_db.get = Mock(return_value=None)
        update_data = ServerUpdate(name="updated_server")
        test_user_email = "user@example.com"

        with pytest.raises(ServerError) as exc:
            await server_service.update_server(test_db, 999, update_data, test_user_email)
        assert "Server not found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_update_server_name_conflict(self, server_service, mock_server, test_db):
        import types
        from mcpgateway.services.server_service import ServerNameConflictError

        # Mock PermissionService to bypass ownership checks (this test is about name conflicts)
        with patch("mcpgateway.services.permission_service.PermissionService") as mock_perm_service_class:
            mock_perm_service = mock_perm_service_class.return_value
            mock_perm_service.check_resource_ownership = AsyncMock(return_value=True)

            # --- PRIVATE: allow same name across users/teams (should NOT raise ServerNameConflictError) --- #
            server_private = mock_server
            server_private.id = "1"
            server_private.name = "other_server"
            server_private.visibility = "private"
            server_private.team_id = "teamA"

            # Simulate no conflict found (should not raise)
            test_db.get = Mock(return_value=server_private)
            mock_scalar = Mock()
            mock_scalar.scalar_one_or_none.return_value = None
            # get_for_update may use db.execute when loader options are present;
            # ensure the first execute() call (get_for_update) returns the server,
            # while the second call (name conflict check) returns `None`.
            test_db.execute = Mock(side_effect=[Mock(scalar_one_or_none=Mock(return_value=server_private)), mock_scalar])
            test_db.rollback = Mock()
            test_db.refresh = Mock()

            # Should not raise ServerNameConflictError for private, but should raise IntegrityError for duplicate name
            from sqlalchemy.exc import IntegrityError

            test_db.commit = Mock(side_effect=IntegrityError("Duplicate name", None, None))

            test_user_email = "user@example.com"

            with pytest.raises(IntegrityError):
                await server_service.update_server(
                    test_db,
                    "1",
                    ServerUpdate(name="existing_server", visibility="private"),
                    test_user_email,
                )

            # --- TEAM: restrict within team only (should raise ServerNameConflictError) --- #
            server_team = mock_server
            server_team.id = "2"
            server_team.name = "other_server"
            server_team.visibility = "team"
            server_team.team_id = "teamA"

            conflict_team_server = types.SimpleNamespace(id="3", name="existing_server", enabled=True, visibility="team", team_id="teamA")

            test_db.get = Mock(return_value=server_team)
            mock_scalar = Mock()
            mock_scalar.scalar_one_or_none.return_value = conflict_team_server
            # Ensure get_for_update returns the server_team first, then the
            # name-conflict query returns the conflicting server.
            test_db.execute = Mock(side_effect=[Mock(scalar_one_or_none=Mock(return_value=server_team)), mock_scalar])
            test_db.rollback = Mock()
            test_db.refresh = Mock()

            test_user_email = "user@example.com"

            with pytest.raises(ServerNameConflictError) as exc:
                await server_service.update_server(
                    test_db,
                    "2",
                    ServerUpdate(name="existing_server", visibility="team", team_id="teamA"),
                    test_user_email,
                )
            assert "Team Server already exists with name" in str(exc.value)
            test_db.rollback.assert_called()

            # --- PUBLIC: restrict globally (should raise ServerNameConflictError) --- #
            server_public = mock_server
            server_public.id = "4"
            server_public.name = "other_server"
            server_public.visibility = "public"
            server_public.team_id = None

            conflict_public_server = types.SimpleNamespace(id="5", name="existing_server", enabled=True, visibility="public", team_id=None)

            test_db.get = Mock(return_value=server_public)
            mock_scalar = Mock()
            mock_scalar.scalar_one_or_none.return_value = conflict_public_server
            # Ensure get_for_update returns the server_public first, then the
            # name-conflict query returns the conflicting public server.
            test_db.execute = Mock(side_effect=[Mock(scalar_one_or_none=Mock(return_value=server_public)), mock_scalar])
            test_db.rollback = Mock()
            test_db.refresh = Mock()

            test_user_email = "user@example.com"

            with pytest.raises(ServerNameConflictError) as exc:
                await server_service.update_server(
                    test_db,
                    "4",
                    ServerUpdate(name="existing_server", visibility="public"),
                    test_user_email,
                )
            assert "Public Server already exists with name" in str(exc.value)
            test_db.rollback.assert_called()

    # -------------------------- set state --------------------------------- #
    @pytest.mark.asyncio
    async def test_set_server_state(self, server_service, mock_server, test_db):
        mock_server.team_id = 1
        test_db.get = Mock(return_value=mock_server)
        # Ensure get_for_update returns the mocked server when loader options are used
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_activated = AsyncMock()
        server_service._notify_server_deactivated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=False,
                associated_tools=["101"],
                associated_resources=["201"],
                associated_prompts=["301"],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        result = await server_service.set_server_state(test_db, 1, activate=False)

        # get_for_update may use `db.get(..., options=...)` or execute a select;
        # accept either approach.
        assert test_db.get.called or test_db.execute.called
        assert test_db.commit.call_count == 1
        test_db.refresh.assert_called_once()
        server_service._notify_server_deactivated.assert_called_once()
        assert result.enabled is False

    @pytest.mark.asyncio
    async def test_set_server_state_activate(self, server_service, mock_server, test_db):
        """Test activating a server."""
        mock_server.enabled = False
        mock_server.team_id = 1
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_activated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        result = await server_service.set_server_state(test_db, "1", activate=True)

        assert test_db.execute.called
        assert test_db.commit.call_count == 1
        test_db.refresh.assert_called_once()
        server_service._notify_server_activated.assert_called_once()
        assert result.enabled is True

    @pytest.mark.asyncio
    async def test_set_server_state_with_email_team(self, server_service, mock_server, test_db):
        """Test that email_team relationship is properly loaded with selectinload."""
        from mcpgateway.db import EmailTeam

        mock_team = Mock(spec=EmailTeam)
        mock_team.id = 1
        mock_team.name = "Test Team"
        mock_server.team_id = 1
        mock_server.email_team = mock_team

        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_deactivated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=False,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        result = await server_service.set_server_state(test_db, "1", activate=False)

        # Verify the server was retrieved with proper options (selectinload for email_team)
        assert test_db.execute.called
        assert result.enabled is False

    # --------------------------- delete -------------------------------- #
    @pytest.mark.asyncio
    async def test_delete_server(self, server_service, mock_server, test_db):
        test_db.get = Mock(return_value=mock_server)
        test_db.delete = Mock()
        test_db.commit = Mock()
        server_service._notify_server_deleted = AsyncMock()

        await server_service.delete_server(test_db, 1)

        test_db.get.assert_called_once_with(DbServer, 1)
        test_db.delete.assert_called_once_with(mock_server)
        test_db.commit.assert_called_once()
        server_service._notify_server_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_server_purge_metrics(self, server_service, mock_server, test_db):
        test_db.get = Mock(return_value=mock_server)
        test_db.delete = Mock()
        test_db.commit = Mock()
        test_db.execute = Mock()
        server_service._notify_server_deleted = AsyncMock()

        await server_service.delete_server(test_db, 1, purge_metrics=True)

        assert test_db.execute.call_count == 2
        test_db.delete.assert_called_once_with(mock_server)
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_server_not_found(self, server_service, test_db):
        test_db.get = Mock(return_value=None)
        with pytest.raises(ServerError) as exc:
            await server_service.delete_server(test_db, 999)
        assert "Server not found" in str(exc.value)

    # --------------------------- metrics ------------------------------- #
    @pytest.mark.asyncio
    async def test_reset_metrics(self, server_service, test_db):
        test_db.execute = Mock()
        test_db.commit = Mock()
        await server_service.reset_metrics(test_db)
        assert test_db.execute.call_count == 2
        test_db.commit.assert_called_once()

    # --------------------------- UUID normalization -------------------- #
    @pytest.mark.asyncio
    async def test_register_server_uuid_normalization_standard_format(self, server_service, test_db):
        """Test server registration with standard UUID format (with dashes) normalizes to hex format."""
        # Standard
        import uuid as uuid_module

        # Standard UUID format (with dashes)
        standard_uuid = "550e8400-e29b-41d4-a716-446655440000"
        expected_hex_uuid = str(uuid_module.UUID(standard_uuid)).replace("-", "")

        # No existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Capture the server being added to verify UUID normalization
        captured_server = None

        def capture_add(server):
            nonlocal captured_server
            captured_server = server

        test_db.add = Mock(side_effect=capture_add)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        test_db.get = Mock(return_value=None)  # No associated items

        # Mock service methods
        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id=expected_hex_uuid,
                name="UUID Normalization Test",
                description="Test UUID normalization",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(id=standard_uuid, name="UUID Normalization Test", description="Test UUID normalization")

        # Call the service method
        result = await server_service.register_server(test_db, server_create)

        # Verify UUID was normalized to hex format
        assert captured_server is not None
        assert captured_server.id == expected_hex_uuid
        assert len(captured_server.id) == 32
        assert "-" not in captured_server.id
        assert result.id == expected_hex_uuid

        # Verify other operations were called
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_server_uuid_normalization_hex_format(self, server_service, test_db):
        """Test server registration with hex UUID format works correctly."""
        # Standard
        import uuid as uuid_module

        # Standard UUID that will be normalized
        standard_uuid = "123e4567-e89b-12d3-a456-426614174000"
        expected_hex_uuid = str(uuid_module.UUID(standard_uuid)).replace("-", "")

        # No existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Capture the server being added to verify UUID normalization
        captured_server = None

        def capture_add(server):
            nonlocal captured_server
            captured_server = server

        test_db.add = Mock(side_effect=capture_add)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        test_db.get = Mock(return_value=None)  # No associated items

        # Mock service methods
        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id=expected_hex_uuid,
                name="Hex UUID Test",
                description="Test hex UUID handling",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(
            id=standard_uuid,  # Will be normalized by the service
            name="Hex UUID Test",
            description="Test hex UUID handling",
        )

        # Call the service method
        result = await server_service.register_server(test_db, server_create)

        # Verify UUID was normalized correctly
        assert captured_server is not None
        assert captured_server.id == expected_hex_uuid
        assert len(captured_server.id) == 32
        assert "-" not in captured_server.id
        assert captured_server.id.isalnum()
        assert result.id == expected_hex_uuid

    @pytest.mark.asyncio
    async def test_register_server_no_uuid_auto_generation(self, server_service, test_db):
        """Test server registration without UUID allows auto-generation."""
        # No existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Capture the server being added
        captured_server = None

        def capture_add(server):
            nonlocal captured_server
            captured_server = server

        test_db.add = Mock(side_effect=capture_add)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        test_db.get = Mock(return_value=None)  # No associated items

        # Mock service methods
        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="auto_generated_uuid_32_chars_hex",
                name="Auto UUID Test",
                description="Test auto UUID generation",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(name="Auto UUID Test", description="Test auto UUID generation")
        # Verify no UUID is set
        assert server_create.id is None

        # Call the service method
        result = await server_service.register_server(test_db, server_create)

        # Verify no UUID was set on the server (letting DB handle auto-generation)
        assert captured_server is not None
        assert captured_server.id is None  # Service doesn't set UUID when not provided
        assert result.id == "auto_generated_uuid_32_chars_hex"

    @pytest.mark.asyncio
    async def test_register_server_uuid_normalization_error_handling(self, server_service, test_db):
        """Test that UUID normalization handles errors gracefully."""
        # No existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock database rollback for error scenarios
        test_db.rollback = Mock()

        server_create = ServerCreate(id="550e8400-e29b-41d4-a716-446655440000", name="Error Test", description="Test error handling")

        # Simulate an error during database operations
        test_db.add = Mock(side_effect=Exception("Database error"))

        # The service should catch the exception and raise ServerError
        with pytest.raises(ServerError) as exc:
            await server_service.register_server(test_db, server_create)

        assert "Failed to register server" in str(exc.value)
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_server_uuid_normalization(self, server_service, test_db):
        """Test server update with UUID normalization."""
        # Standard
        import uuid as uuid_module

        # Mock existing server
        existing_server = MagicMock(spec=DbServer)
        existing_server.id = "oldserverid"
        existing_server.name = "Old Name"
        existing_server.enabled = True
        existing_server.tools = []
        existing_server.resources = []
        existing_server.prompts = []

        # Add ownership fields for RBAC
        existing_server.owner_email = "user@example.com"
        existing_server.team_id = None
        existing_server.visibility = "public"

        # New UUID to update to
        new_standard_uuid = "550e8400-e29b-41d4-a716-446655440000"
        expected_hex_uuid = str(uuid_module.UUID(new_standard_uuid)).replace("-", "")

        # Mock db.get to return existing server for the initial lookup, then None for the UUID check
        test_db.get = Mock(side_effect=lambda cls, _id, options=None: existing_server if _id == "oldserverid" else None)

        # Mock name conflict check and ensure initial get_for_update returns the existing server
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        mock_result_get_server = Mock(scalar_one_or_none=Mock(return_value=existing_server))
        # Sequence of execute() results: 1) get_for_update -> existing_server,
        # 2) _is_user_admin -> None, 3) name-conflict check -> None
        test_db.execute = Mock(side_effect=[mock_result_get_server, Mock(scalar_one_or_none=Mock(return_value=None)), mock_scalar])

        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock service methods
        server_service._notify_server_updated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id=expected_hex_uuid,
                name="Updated Server",
                description="Updated description",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_update = ServerUpdate(id=new_standard_uuid, name="Updated Server", description="Updated description")

        test_user_email = "user@example.com"

        # Call the service method
        result = await server_service.update_server(test_db, "oldserverid", server_update, test_user_email)

        # Verify UUID was set correctly (note: actual normalization happens at create time)
        # The update method currently just sets the ID directly
        assert existing_server.id == expected_hex_uuid  # Update doesn't normalize currently
        assert result.id == expected_hex_uuid
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

    def test_uuid_normalization_edge_cases(self, server_service):
        """Test edge cases in UUID normalization logic."""
        # Standard
        import uuid as uuid_module

        # Test various UUID formats that should all normalize correctly
        test_cases = [
            {"input": "550e8400-e29b-41d4-a716-446655440000", "expected": "550e8400e29b41d4a716446655440000", "description": "Standard lowercase UUID"},
            {"input": "550E8400-E29B-41D4-A716-446655440000", "expected": "550e8400e29b41d4a716446655440000", "description": "Uppercase UUID (should normalize to lowercase)"},
            {"input": "00000000-0000-0000-0000-000000000000", "expected": "00000000000000000000000000000000", "description": "Nil UUID"},
            {"input": "ffffffff-ffff-ffff-ffff-ffffffffffff", "expected": "ffffffffffffffffffffffffffffffff", "description": "Max UUID"},
        ]

        for case in test_cases:
            # Simulate the exact normalization logic from server_service.py
            normalized = str(uuid_module.UUID(case["input"])).replace("-", "")
            assert normalized == case["expected"], f"Failed for {case['description']}: expected {case['expected']}, got {normalized}"
            assert len(normalized) == 32
            # Check that any alphabetic characters are lowercase
            assert normalized.islower() or not any(c.isalpha() for c in normalized)
            assert normalized.isalnum()

    @pytest.mark.asyncio
    async def test_list_servers_with_tags(self, server_service, mock_server):
        """Test listing servers with tag filtering."""
        # Third-Party

        # Mock query chain
        mock_query = MagicMock()
        mock_query.options.return_value = mock_query  # For selectinload
        mock_query.where.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [mock_server]
        session.commit.return_value = None

        bind = MagicMock()
        bind.dialect = MagicMock()
        bind.dialect.name = "sqlite"  # or "postgresql" or "mysql"
        session.get_bind.return_value = bind

        with patch("mcpgateway.services.server_service.select", return_value=mock_query):
            with patch("mcpgateway.services.server_service.json_contains_tag_expr") as mock_json_contains:
                # return a fake condition object that query.where will accept
                fake_condition = MagicMock()
                mock_json_contains.return_value = fake_condition
                mock_team = MagicMock()
                mock_team.name = "test-team"
                session.query().filter().first.return_value = mock_team

                result = await server_service.list_servers(session, tags=["test", "production"])

                # helper should be called once with the tags list (not once per tag)
                mock_json_contains.assert_called_once()  # called exactly once
                called_args = mock_json_contains.call_args[0]  # positional args tuple
                assert called_args[0] is session  # session passed through
                # third positional arg is the tags list (signature: session, col, values, match_any=True)
                assert called_args[2] == ["test", "production"]
                # and the fake condition returned must have been passed to where()
                mock_query.where.assert_called_with(fake_condition)
                # finally, your service should return a tuple (list, cursor)
                assert isinstance(result, tuple)
                servers, cursor = result
                assert isinstance(servers, list)
                assert len(servers) == 1
                assert cursor is None

    # --------------------------- OAuth Configuration -------------------- #
    @pytest.mark.asyncio
    async def test_register_server_with_oauth_config(self, server_service, test_db):
        """Test server registration with OAuth configuration for RFC 9728 support."""
        # No existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Capture the server being added
        captured_server = None

        def capture_add(server):
            nonlocal captured_server
            captured_server = server

        test_db.add = Mock(side_effect=capture_add)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        test_db.get = Mock(return_value=None)

        # Define OAuth configuration
        oauth_config = {
            "authorization_server": "https://idp.example.com",
            "token_endpoint": "https://idp.example.com/oauth/token",
            "authorization_endpoint": "https://idp.example.com/oauth/authorize",
            "scopes_supported": ["openid", "profile", "email"],
        }

        # Mock service methods
        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="OAuth Server",
                description="Server with OAuth enabled",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                oauth_enabled=True,
                oauth_config=oauth_config,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(
            name="OAuth Server",
            description="Server with OAuth enabled",
            oauth_enabled=True,
            oauth_config=oauth_config,
        )

        # Call the service method
        result = await server_service.register_server(test_db, server_create)

        # Verify OAuth config was stored
        assert captured_server is not None
        assert captured_server.oauth_enabled is True
        assert captured_server.oauth_config == oauth_config
        assert result.oauth_enabled is True
        assert result.oauth_config == oauth_config
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_server_without_oauth_config(self, server_service, test_db):
        """Test server registration without OAuth configuration (default behavior)."""
        # No existing server with the same name
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Capture the server being added
        captured_server = None

        def capture_add(server):
            nonlocal captured_server
            captured_server = server

        test_db.add = Mock(side_effect=capture_add)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        test_db.get = Mock(return_value=None)

        # Mock service methods
        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="Non-OAuth Server",
                description="Server without OAuth",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                oauth_enabled=False,
                oauth_config=None,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(
            name="Non-OAuth Server",
            description="Server without OAuth",
        )

        # Call the service method
        result = await server_service.register_server(test_db, server_create)

        # Verify OAuth config is not set
        assert captured_server is not None
        assert getattr(captured_server, "oauth_enabled", False) is False
        assert getattr(captured_server, "oauth_config", None) is None
        assert result.oauth_enabled is False
        assert result.oauth_config is None

    @pytest.mark.asyncio
    async def test_update_server_oauth_config(self, server_service, mock_server, test_db):
        """Test updating server with OAuth configuration."""
        # Setup existing server without OAuth
        mock_server.oauth_enabled = False
        mock_server.oauth_config = None

        test_db.get = Mock(return_value=mock_server)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Ensure get_for_update (which uses db.execute when loader options
        # are present) returns our mocked server instance.
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))

        # Define new OAuth configuration
        new_oauth_config = {
            "authorization_server": "https://auth.example.com",
            "scopes_supported": ["read", "write"],
        }

        server_service._notify_server_updated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                oauth_enabled=True,
                oauth_config=new_oauth_config,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_update = ServerUpdate(
            oauth_enabled=True,
            oauth_config=new_oauth_config,
        )

        test_user_email = "user@example.com"
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)):
            result = await server_service.update_server(test_db, "1", server_update, test_user_email)

        # Verify OAuth config was updated
        assert mock_server.oauth_enabled is True
        assert mock_server.oauth_config == new_oauth_config
        assert result.oauth_enabled is True
        assert result.oauth_config == new_oauth_config
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_server_disable_oauth(self, server_service, mock_server, test_db):
        """Test disabling OAuth on a server."""
        # Setup existing server with OAuth enabled
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {"authorization_server": "https://auth.example.com"}

        test_db.get = Mock(return_value=mock_server)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Ensure get_for_update (which uses db.execute when loader options
        # are present) returns our mocked server instance.
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))

        server_service._notify_server_updated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                oauth_enabled=False,
                oauth_config=None,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_update = ServerUpdate(
            oauth_enabled=False,
            oauth_config=None,
        )

        test_user_email = "user@example.com"
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)):
            result = await server_service.update_server(test_db, "1", server_update, test_user_email)

        # Verify OAuth was disabled
        assert mock_server.oauth_enabled is False
        assert mock_server.oauth_config is None
        assert result.oauth_enabled is False
        assert result.oauth_config is None

    @pytest.mark.asyncio
    async def test_server_oauth_config_in_read(self, server_service, mock_server, test_db):
        """Test that OAuth config is included in server read response."""
        # Setup server with OAuth config
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "authorization_server": "https://idp.example.com",
            "scopes_supported": ["openid"],
        }

        test_db.get = Mock(return_value=mock_server)

        # Manually call convert_server_to_read to test the conversion
        # This test verifies the data flow when OAuth fields are present
        server_read = server_service.convert_server_to_read(mock_server)

        # Verify OAuth fields are included in the read model
        assert server_read.oauth_enabled is True
        assert server_read.oauth_config is not None
        assert server_read.oauth_config["authorization_server"] == "https://idp.example.com"

    # ---- get_top_servers ---- #
    @pytest.mark.asyncio
    async def test_get_top_servers_cache_hit(self, server_service):
        """Cache hit returns cached data without DB query."""
        cached = [{"id": "s1", "name": "srv"}]
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True),
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_cache,
        ):
            mock_cache.get_async = AsyncMock(return_value=cached)
            result = await server_service.get_top_servers(MagicMock(), limit=5)
        assert result == cached

    @pytest.mark.asyncio
    async def test_get_top_servers_cache_miss(self, server_service):
        """Cache miss queries DB and stores result."""
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True),
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_cache,
            patch("mcpgateway.services.metrics_query_service.get_top_performers_combined", return_value=[]),
            patch("mcpgateway.services.server_service.build_top_performers", return_value=[]),
        ):
            mock_cache.get_async = AsyncMock(return_value=None)
            mock_cache.set_async = AsyncMock()
            result = await server_service.get_top_servers(MagicMock(), limit=3)
        assert result == []
        mock_cache.set_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_top_servers_cache_disabled(self, server_service):
        """When cache is disabled, always queries DB."""
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=False),
            patch("mcpgateway.services.metrics_query_service.get_top_performers_combined", return_value=[]),
            patch("mcpgateway.services.server_service.build_top_performers", return_value=[]),
        ):
            result = await server_service.get_top_servers(MagicMock())
        assert result == []

    # ---- aggregate_metrics ---- #
    @pytest.mark.asyncio
    async def test_aggregate_metrics_cache_hit(self, server_service):
        """Cache hit returns ServerMetrics from cached dict."""
        cached = {
            "total_executions": 10,
            "successful_executions": 8,
            "failed_executions": 2,
            "failure_rate": 0.2,
            "min_response_time": 0.01,
            "max_response_time": 1.0,
            "avg_response_time": 0.5,
            "last_execution_time": None,
        }
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True),
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_cache,
        ):
            mock_cache.get_async = AsyncMock(return_value=cached)
            result = await server_service.aggregate_metrics(MagicMock())
        assert result.total_executions == 10
        assert result.failed_executions == 2

    @pytest.mark.asyncio
    async def test_aggregate_metrics_cache_miss(self, server_service):
        """Cache miss queries and caches result."""
        mock_result = MagicMock()
        mock_result.total_executions = 5
        mock_result.successful_executions = 4
        mock_result.failed_executions = 1
        mock_result.failure_rate = 0.2
        mock_result.min_response_time = 0.01
        mock_result.max_response_time = 1.0
        mock_result.avg_response_time = 0.5
        mock_result.last_execution_time = None
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True),
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_cache,
            patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result),
        ):
            mock_cache.get_async = AsyncMock(return_value=None)
            mock_cache.set_async = AsyncMock()
            result = await server_service.aggregate_metrics(MagicMock())
        assert result.total_executions == 5
        mock_cache.set_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregate_metrics_cache_disabled(self, server_service):
        """When cache disabled, queries DB directly."""
        mock_result = MagicMock()
        mock_result.total_executions = 3
        mock_result.successful_executions = 3
        mock_result.failed_executions = 0
        mock_result.failure_rate = 0.0
        mock_result.min_response_time = 0.1
        mock_result.max_response_time = 0.5
        mock_result.avg_response_time = 0.3
        mock_result.last_execution_time = None
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=False),
            patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result),
        ):
            result = await server_service.aggregate_metrics(MagicMock())
        assert result.total_executions == 3

    # ---- notification events ---- #
    @pytest.mark.asyncio
    async def test_notify_server_added(self, server_service, mock_server):
        """_notify_server_added publishes server_added event."""
        server_service._event_subscribers = [asyncio.Queue()]
        await server_service._notify_server_added(mock_server)
        event = server_service._event_subscribers[0].get_nowait()
        assert event["type"] == "server_added"
        assert event["data"]["id"] == "1"
        assert event["data"]["name"] == "test_server"
        assert "101" in event["data"]["associated_tools"]

    @pytest.mark.asyncio
    async def test_notify_server_updated(self, server_service, mock_server):
        """_notify_server_updated publishes server_updated event."""
        server_service._event_subscribers = [asyncio.Queue()]
        await server_service._notify_server_updated(mock_server)
        event = server_service._event_subscribers[0].get_nowait()
        assert event["type"] == "server_updated"
        assert event["data"]["id"] == "1"

    @pytest.mark.asyncio
    async def test_notify_server_activated(self, server_service, mock_server):
        """_notify_server_activated publishes server_activated event."""
        server_service._event_subscribers = [asyncio.Queue()]
        await server_service._notify_server_activated(mock_server)
        event = server_service._event_subscribers[0].get_nowait()
        assert event["type"] == "server_activated"
        assert event["data"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_notify_server_deactivated(self, server_service, mock_server):
        """_notify_server_deactivated publishes server_deactivated event."""
        server_service._event_subscribers = [asyncio.Queue()]
        await server_service._notify_server_deactivated(mock_server)
        event = server_service._event_subscribers[0].get_nowait()
        assert event["type"] == "server_deactivated"
        assert event["data"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_notify_server_deleted(self, server_service):
        """_notify_server_deleted publishes server_deleted event."""
        server_service._event_subscribers = [asyncio.Queue()]
        info = {"id": "1", "name": "deleted_server"}
        await server_service._notify_server_deleted(info)
        event = server_service._event_subscribers[0].get_nowait()
        assert event["type"] == "server_deleted"
        assert event["data"]["id"] == "1"

    @pytest.mark.asyncio
    async def test_publish_event_multiple_subscribers(self, server_service):
        """_publish_event sends to all subscriber queues."""
        q1, q2 = asyncio.Queue(), asyncio.Queue()
        server_service._event_subscribers = [q1, q2]
        await server_service._publish_event({"type": "test"})
        assert q1.get_nowait()["type"] == "test"
        assert q2.get_nowait()["type"] == "test"

    @pytest.mark.asyncio
    async def test_subscribe_events(self, server_service):
        """subscribe_events yields events and cleans up on exit."""
        server_service._event_subscribers = []

        async def _consume():
            results = []
            async for event in server_service.subscribe_events():
                results.append(event)
                if len(results) >= 2:
                    break
            return results

        # Start consumer in background
        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)  # Let it register

        assert len(server_service._event_subscribers) == 1
        await server_service._event_subscribers[0].put({"type": "e1"})
        await server_service._event_subscribers[0].put({"type": "e2"})

        results = await task
        assert len(results) == 2
        assert results[0]["type"] == "e1"

    # ---- get_oauth_protected_resource_metadata ---- #
    def test_get_oauth_metadata_not_found(self, server_service):
        """Raises ServerNotFoundError for non-existent server."""
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(ServerNotFoundError):
            server_service.get_oauth_protected_resource_metadata(db, "s1", "https://gw.com/s1")

    def test_get_oauth_metadata_disabled_server(self, server_service, mock_server):
        """Raises ServerNotFoundError for disabled server."""
        mock_server.enabled = False
        db = MagicMock()
        db.get.return_value = mock_server
        with pytest.raises(ServerNotFoundError):
            server_service.get_oauth_protected_resource_metadata(db, "1", "https://gw.com/1")

    def test_get_oauth_metadata_non_public(self, server_service, mock_server):
        """Raises ServerNotFoundError for non-public server."""
        mock_server.visibility = "private"
        db = MagicMock()
        db.get.return_value = mock_server
        with pytest.raises(ServerNotFoundError):
            server_service.get_oauth_protected_resource_metadata(db, "1", "https://gw.com/1")

    def test_get_oauth_metadata_oauth_not_enabled(self, server_service, mock_server):
        """Raises ServerError when OAuth not enabled."""
        mock_server.visibility = "public"
        mock_server.oauth_enabled = False
        db = MagicMock()
        db.get.return_value = mock_server
        with pytest.raises(ServerError):
            server_service.get_oauth_protected_resource_metadata(db, "1", "https://gw.com/1")

    def test_get_oauth_metadata_no_config(self, server_service, mock_server):
        """Raises ServerError when no OAuth config."""
        mock_server.visibility = "public"
        mock_server.oauth_enabled = True
        mock_server.oauth_config = None
        db = MagicMock()
        db.get.return_value = mock_server
        with pytest.raises(ServerError):
            server_service.get_oauth_protected_resource_metadata(db, "1", "https://gw.com/1")

    def test_get_oauth_metadata_no_auth_server(self, server_service, mock_server):
        """Raises ServerError when no authorization_servers in config."""
        mock_server.visibility = "public"
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {"scopes_supported": ["read"]}
        db = MagicMock()
        db.get.return_value = mock_server
        with pytest.raises(ServerError, match="authorization_server not configured"):
            server_service.get_oauth_protected_resource_metadata(db, "1", "https://gw.com/1")

    def test_get_oauth_metadata_success_single_server(self, server_service, mock_server):
        """Returns RFC 9728 metadata with singular authorization_server config (wrapped in array)."""
        mock_server.visibility = "public"
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "authorization_server": "https://idp.example.com",
            "scopes_supported": ["openid", "profile"],
        }
        db = MagicMock()
        db.get.return_value = mock_server
        result = server_service.get_oauth_protected_resource_metadata(db, "1", "https://gw.com/1")
        assert result["resource"] == "https://gw.com/1"
        # RFC 9728 Section 2: authorization_servers is a JSON array
        assert result["authorization_servers"] == ["https://idp.example.com"]
        assert isinstance(result["authorization_servers"], list)
        assert result["bearer_methods_supported"] == ["header"]
        assert result["scopes_supported"] == ["openid", "profile"]

    def test_get_oauth_metadata_success_multiple_servers(self, server_service, mock_server):
        """Returns RFC 9728 metadata preserving all authorization_servers from plural config."""
        mock_server.visibility = "public"
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "authorization_servers": ["https://idp1.com", "https://idp2.com"],
        }
        db = MagicMock()
        db.get.return_value = mock_server
        result = server_service.get_oauth_protected_resource_metadata(db, "1", "https://gw.com/1")
        # RFC 9728 Section 2: authorization_servers preserves all servers
        assert result["authorization_servers"] == ["https://idp1.com", "https://idp2.com"]
        assert isinstance(result["authorization_servers"], list)
        assert "scopes_supported" not in result

    # ---- list_servers_for_user edge cases ---- #
    @pytest.mark.asyncio
    async def test_list_servers_for_user_team_no_access(self, server_service, test_db):
        """Team filter with no access returns empty list."""
        with patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS:
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_tms
            result = await server_service.list_servers_for_user(test_db, "user@test.com", team_id="team-xyz")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_servers_for_user_team_with_access(self, server_service, test_db, mock_server):
        """Team filter with access returns filtered servers."""
        mock_team = MagicMock()
        mock_team.id = "team-1"
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_server]
        test_db.execute = MagicMock(return_value=exec_result)
        test_db.commit = MagicMock()

        server_service.convert_server_to_read = Mock(return_value="converted")
        with patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS:
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[mock_team])
            MockTMS.return_value = mock_tms
            result = await server_service.list_servers_for_user(test_db, "user@test.com", team_id="team-1")
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_list_servers_for_user_visibility_filter(self, server_service, test_db, mock_server):
        """Visibility filter is applied."""
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_server]
        test_db.execute = MagicMock(return_value=exec_result)
        test_db.commit = MagicMock()

        server_service.convert_server_to_read = Mock(return_value="srv")
        with patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS:
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_tms
            result = await server_service.list_servers_for_user(test_db, "user@test.com", visibility="public")
        assert result == ["srv"]

    @pytest.mark.asyncio
    async def test_list_servers_for_user_conversion_error(self, server_service, test_db, mock_server):
        """Conversion error for one server doesn't fail entire list."""
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_server, mock_server]
        test_db.execute = MagicMock(return_value=exec_result)
        test_db.commit = MagicMock()

        server_service.convert_server_to_read = Mock(side_effect=[ValueError("bad"), "ok"])
        with patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS:
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_tms
            result = await server_service.list_servers_for_user(test_db, "user@test.com")
        assert result == ["ok"]

    @pytest.mark.asyncio
    async def test_list_servers_for_user_include_inactive(self, server_service, test_db, mock_server):
        """include_inactive=True doesn't filter by enabled."""
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_server]
        test_db.execute = MagicMock(return_value=exec_result)
        test_db.commit = MagicMock()

        server_service.convert_server_to_read = Mock(return_value="srv")
        with patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS:
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_tms
            result = await server_service.list_servers_for_user(test_db, "user@test.com", include_inactive=True)
        assert result == ["srv"]

    @pytest.mark.asyncio
    async def test_disable_oauth_clears_config_even_when_both_provided(self, server_service, mock_server, test_db):
        """Test that disabling OAuth clears config even when oauth_config is also provided in the update.

        This tests the fix for the logic ordering issue where oauth_enabled=False would clear
        oauth_config, but then oauth_config would be reassigned if also present in the update.
        """
        # Setup server with OAuth already enabled
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "authorization_servers": ["https://original-idp.example.com"],
            "scopes_supported": ["openid"],
        }

        # Mock get_for_update (which uses db.execute when loader options are present)
        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=mock_server)))
        test_db.refresh = Mock()

        server_service._notify_server_updated = AsyncMock()
        server_service.convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                oauth_enabled=False,
                oauth_config=None,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        # Update with BOTH oauth_enabled=False AND a new oauth_config
        # The expectation is that oauth_config should be cleared, NOT replaced
        server_update = ServerUpdate(
            oauth_enabled=False,
            oauth_config={
                "authorization_servers": ["https://new-idp.example.com"],
                "scopes_supported": ["profile"],
            },
        )

        test_user_email = "user@example.com"
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)):
            result = await server_service.update_server(test_db, "1", server_update, test_user_email)

        # Verify OAuth was disabled AND config was cleared (not replaced)
        assert mock_server.oauth_enabled is False
        assert mock_server.oauth_config is None
        assert result.oauth_enabled is False
        assert result.oauth_config is None


# --------------------------------------------------------------------------- #
#  Additional coverage: convert_server_to_read metrics                        #
# --------------------------------------------------------------------------- #


class TestConvertServerToReadMetrics:
    """Cover lines 306-337: metrics aggregation in convert_server_to_read."""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    def _make_server(self, metrics=None):
        from types import SimpleNamespace

        s = SimpleNamespace(
            id="srv-1",
            name="test",
            description="desc",
            icon=None,
            enabled=True,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
            team_id=None,
            team=None,
            owner_email=None,
            visibility="public",
            created_by="admin",
            modified_by=None,
            tags=[],
            tools=[],
            resources=[],
            prompts=[],
            a2a_agents=[],
            metrics=metrics or [],
            oauth_enabled=False,
            oauth_config=None,
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            modified_from_ip=None,
            modified_via=None,
            modified_user_agent=None,
            import_batch_id=None,
            federation_source=None,
            version=1,
        )
        return s

    def test_metrics_aggregation_with_data(self, server_service):
        """Metrics with multiple entries are aggregated correctly."""
        from datetime import datetime, timezone

        m1 = MagicMock()
        m1.is_success = True
        m1.response_time = 0.2
        m1.timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)

        m2 = MagicMock()
        m2.is_success = False
        m2.response_time = 0.8
        m2.timestamp = datetime(2025, 1, 2, tzinfo=timezone.utc)

        m3 = MagicMock()
        m3.is_success = True
        m3.response_time = 0.5
        m3.timestamp = datetime(2025, 1, 3, tzinfo=timezone.utc)

        server = self._make_server(metrics=[m1, m2, m3])
        result = server_service.convert_server_to_read(server, include_metrics=True)

        assert result.metrics.total_executions == 3
        assert result.metrics.successful_executions == 2
        assert result.metrics.failed_executions == 1
        assert result.metrics.min_response_time == 0.2
        assert result.metrics.max_response_time == 0.8
        assert abs(result.metrics.avg_response_time - 0.5) < 0.01
        assert result.metrics.last_execution_time == datetime(2025, 1, 3, tzinfo=timezone.utc)

    def test_metrics_none_when_not_requested(self, server_service):
        """Metrics are None when include_metrics=False."""
        server = self._make_server()
        result = server_service.convert_server_to_read(server, include_metrics=False)
        assert result.metrics is None

    def test_metrics_empty_list(self, server_service):
        """Empty metrics list produces zero counts and None avg."""
        server = self._make_server(metrics=[])
        result = server_service.convert_server_to_read(server, include_metrics=True)
        assert result.metrics.total_executions == 0
        assert result.metrics.avg_response_time is None


# --------------------------------------------------------------------------- #
#  Additional coverage: register_server bulk associations                     #
# --------------------------------------------------------------------------- #


class TestRegisterServerBulkAssociations:
    """Cover lines 531-602: bulk tool/resource/prompt/a2a association in register_server."""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    def _make_mock_db_server(self):
        """Return a MagicMock that stands in for DbServer with simple list attributes."""
        s = MagicMock()
        s.id = "new-id"
        s.name = "test"
        s.tools = []
        s.resources = []
        s.prompts = []
        s.a2a_agents = []
        s.metrics = []
        s.tags = []
        s.team = None
        s.created_at = "2025-01-01"
        s.updated_at = "2025-01-01"
        s.enabled = True
        return s

    def _add_sa_state(self, *mocks):
        """Add _sa_instance_state to mocks so they can be added to SQLAlchemy relationships."""
        for m in mocks:
            m._sa_instance_state = MagicMock()

    @pytest.mark.asyncio
    async def test_bulk_tools_association(self, server_service, test_db):
        """Multiple tool IDs triggers bulk query path."""
        tool1, tool2 = MagicMock(spec=DbTool), MagicMock(spec=DbTool)
        tool1.id = "t1"
        tool2.id = "t2"
        self._add_sa_state(tool1, tool2)

        sc = ServerCreate(name="bulk-srv", description="desc", associated_tools=["t1", "t2"])

        bulk_result = MagicMock()
        bulk_result.scalars.return_value.all.return_value = [tool1, tool2]
        test_db.execute = Mock(return_value=bulk_result)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            await server_service.register_server(test_db, sc)

        test_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_tools_missing_raises(self, server_service, test_db):
        """Missing tools in bulk query raises ServerError."""
        tool1 = MagicMock(spec=DbTool)
        tool1.id = "t1"
        self._add_sa_state(tool1)

        sc = ServerCreate(name="srv", description="desc", associated_tools=["t1", "t2"])

        bulk_result = MagicMock()
        bulk_result.scalars.return_value.all.return_value = [tool1]  # t2 missing
        test_db.execute = Mock(return_value=bulk_result)
        test_db.add = Mock()
        test_db.rollback = Mock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="do not exist"):
                await server_service.register_server(test_db, sc)

    @pytest.mark.asyncio
    async def test_bulk_resources_association(self, server_service, test_db):
        """Multiple resource IDs triggers bulk query path."""
        r1, r2 = MagicMock(spec=DbResource), MagicMock(spec=DbResource)
        r1.id = "r1"
        r2.id = "r2"
        self._add_sa_state(r1, r2)

        sc = ServerCreate(name="srv-res", description="desc", associated_resources=["r1", "r2"])

        bulk_result = MagicMock()
        bulk_result.scalars.return_value.all.return_value = [r1, r2]
        test_db.execute = Mock(return_value=bulk_result)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            await server_service.register_server(test_db, sc)

        test_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_prompts_missing_raises(self, server_service, test_db):
        """Missing prompts in bulk query raises ServerError."""
        sc = ServerCreate(name="srv", description="desc", associated_prompts=["p1", "p2"])

        bulk_result = MagicMock()
        bulk_result.scalars.return_value.all.return_value = []  # none found
        test_db.execute = Mock(return_value=bulk_result)
        test_db.add = Mock()
        test_db.rollback = Mock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="do not exist"):
                await server_service.register_server(test_db, sc)

    @pytest.mark.asyncio
    async def test_bulk_a2a_agents_association(self, server_service, test_db):
        """Multiple A2A agent IDs triggers bulk query path."""
        from mcpgateway.db import A2AAgent as DbA2AAgent

        a1, a2 = MagicMock(spec=DbA2AAgent), MagicMock(spec=DbA2AAgent)
        a1.id = "a1"
        a1.name = "agent1"
        a2.id = "a2"
        a2.name = "agent2"
        self._add_sa_state(a1, a2)

        sc = ServerCreate(name="srv-agents", description="desc", associated_a2a_agents=["a1", "a2"])

        bulk_result = MagicMock()
        bulk_result.scalars.return_value.all.return_value = [a1, a2]
        test_db.execute = Mock(return_value=bulk_result)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            await server_service.register_server(test_db, sc)

        test_db.add.assert_called_once()


# --------------------------------------------------------------------------- #
#  Additional coverage: register_server IntegrityError handling               #
# --------------------------------------------------------------------------- #


class TestRegisterServerIntegrityError:
    """Cover lines 665-680: IntegrityError path in register_server."""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    @pytest.mark.asyncio
    async def test_integrity_error_on_commit(self, server_service, test_db):
        """IntegrityError during commit is propagated after rollback."""
        from sqlalchemy.exc import IntegrityError

        sc = ServerCreate(name="dup", description="desc")
        test_db.add = Mock()
        test_db.commit = Mock(side_effect=IntegrityError("dup", None, BaseException()))
        test_db.rollback = Mock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(IntegrityError):
                await server_service.register_server(test_db, sc)
        test_db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
#  Additional coverage: list_servers token-based access control               #
# --------------------------------------------------------------------------- #


class TestListServersTokenAccess:
    """Cover lines 798-840: token_teams and user_email access control in list_servers."""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    @pytest.mark.asyncio
    async def test_public_only_token(self, server_service, test_db):
        """token_teams=[] restricts to public-only servers."""
        mock_server = MagicMock()
        mock_server.team_id = None

        with (
            patch.object(server_service, "convert_server_to_read", return_value="converted"),
            patch("mcpgateway.services.server_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.server_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.hash_filters = MagicMock(return_value="test-hash")
            mock_cache_fn.return_value = mock_cache
            mock_paginate.return_value = ([mock_server], None)
            test_db.commit = Mock()

            result, cursor = await server_service.list_servers(test_db, token_teams=[])
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_team_scoped_token(self, server_service, test_db):
        """token_teams=["team-1"] shows public + team servers."""
        mock_server = MagicMock()
        mock_server.team_id = "team-1"

        with (
            patch.object(server_service, "convert_server_to_read", return_value="converted"),
            patch("mcpgateway.services.server_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.server_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.hash_filters = MagicMock(return_value="test-hash")
            mock_cache_fn.return_value = mock_cache
            mock_paginate.return_value = ([mock_server], None)
            test_db.commit = Mock()

            result, cursor = await server_service.list_servers(test_db, token_teams=["team-1"], user_email="user@test.com")
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_user_email_specific_team_no_access(self, server_service, test_db):
        """User requesting specific team they don't belong to gets empty result."""
        with (
            patch("mcpgateway.services.server_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS,
        ):
            mock_cache = AsyncMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.hash_filters = MagicMock(return_value="test-hash")
            mock_cache_fn.return_value = mock_cache
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_tms

            result = await server_service.list_servers(test_db, user_email="user@test.com", team_id="team-99")
        assert result == ([], None)

    @pytest.mark.asyncio
    async def test_user_email_specific_team_with_access(self, server_service, test_db):
        """User requesting specific team they belong to gets results."""
        mock_server = MagicMock()
        mock_server.team_id = "team-1"

        mock_team = MagicMock()
        mock_team.id = "team-1"

        with (
            patch.object(server_service, "convert_server_to_read", return_value="converted"),
            patch("mcpgateway.services.server_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS,
            patch("mcpgateway.services.server_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.hash_filters = MagicMock(return_value="test-hash")
            mock_cache_fn.return_value = mock_cache
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[mock_team])
            MockTMS.return_value = mock_tms
            mock_paginate.return_value = ([mock_server], None)
            test_db.commit = Mock()

            result, cursor = await server_service.list_servers(test_db, user_email="user@test.com", team_id="team-1")
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_user_email_general_access_with_teams(self, server_service, test_db):
        """User with teams sees own + public + team servers."""
        mock_server = MagicMock()
        mock_server.team_id = "team-1"

        mock_team = MagicMock()
        mock_team.id = "team-1"

        with (
            patch.object(server_service, "convert_server_to_read", return_value="converted"),
            patch("mcpgateway.services.server_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.server_service.TeamManagementService") as MockTMS,
            patch("mcpgateway.services.server_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.hash_filters = MagicMock(return_value="test-hash")
            mock_cache_fn.return_value = mock_cache
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[mock_team])
            MockTMS.return_value = mock_tms
            mock_paginate.return_value = ([mock_server], None)
            test_db.commit = Mock()

            result, cursor = await server_service.list_servers(test_db, user_email="user@test.com")
        assert result == ["converted"]


# --------------------------------------------------------------------------- #
#  Additional coverage: set_server_state exception handling                   #
# --------------------------------------------------------------------------- #


class TestSetServerStateExceptions:
    """Cover lines 1479-1582: lock conflict, permission check, exception handling."""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    @pytest.mark.asyncio
    async def test_lock_conflict(self, server_service, test_db):
        """OperationalError during row lock raises ServerLockConflictError."""
        from sqlalchemy.exc import OperationalError
        from mcpgateway.services.server_service import ServerLockConflictError

        test_db.execute = Mock(side_effect=OperationalError("locked", None, BaseException()))
        test_db.rollback = Mock()

        with pytest.raises(ServerLockConflictError, match="currently being modified"):
            await server_service.set_server_state(test_db, "srv-1", activate=True)

    @pytest.mark.asyncio
    async def test_permission_denied(self, server_service, test_db):
        """Non-owner user gets PermissionError when toggling state."""
        server = MagicMock(spec=DbServer)
        server.id = "srv-1"
        server.name = "test"
        server.enabled = True

        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=server)))
        test_db.rollback = Mock()

        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=False)):
            with pytest.raises(PermissionError, match="Only the owner"):
                await server_service.set_server_state(test_db, "srv-1", activate=False, user_email="other@test.com")

    @pytest.mark.asyncio
    async def test_generic_exception_wraps_in_server_error(self, server_service, test_db):
        """Generic exception during state change raises wrapped ServerError."""
        server = MagicMock(spec=DbServer)
        server.id = "srv-1"
        server.name = "test"
        server.enabled = True

        test_db.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=server)))
        test_db.commit = Mock(side_effect=RuntimeError("db boom"))
        test_db.rollback = Mock()

        with pytest.raises(ServerError, match="Failed to set server state"):
            await server_service.set_server_state(test_db, "srv-1", activate=False)


# --------------------------------------------------------------------------- #
#  Additional coverage: delete_server permission check                        #
# --------------------------------------------------------------------------- #


class TestDeleteServerPermission:
    """Cover lines 1621-1687: permission check and error logging in delete_server."""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    @pytest.mark.asyncio
    async def test_permission_denied_on_delete(self, server_service, test_db):
        """Non-owner user cannot delete server."""
        server = MagicMock(spec=DbServer)
        server.id = "srv-1"
        server.name = "test"

        test_db.get = Mock(return_value=server)
        test_db.rollback = Mock()

        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=False)):
            with pytest.raises(PermissionError, match="Only the owner"):
                await server_service.delete_server(test_db, "srv-1", user_email="other@test.com")
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_permission_allowed_on_delete(self, server_service, test_db):
        """Owner user can delete server."""
        server = MagicMock(spec=DbServer)
        server.id = "srv-1"
        server.name = "test"

        test_db.get = Mock(return_value=server)
        test_db.delete = Mock()
        test_db.commit = Mock()

        server_service._notify_server_deleted = AsyncMock()

        with (
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)),
            patch("mcpgateway.services.server_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_metrics_cache,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_admin_cache.invalidate_tags = AsyncMock()
            mock_metrics_cache.invalidate_prefix_async = AsyncMock()
            mock_metrics_cache.invalidate_async = AsyncMock()

            await server_service.delete_server(test_db, "srv-1", user_email="owner@test.com")

        test_db.delete.assert_called_once_with(server)
        server_service._notify_server_deleted.assert_called_once()


class TestServerServiceCoverageMissingBranches:
    @pytest.mark.asyncio
    async def test_initialize_and_shutdown(self, server_service):
        server_service._http_client.aclose = AsyncMock()
        await server_service.initialize()
        await server_service.shutdown()
        server_service._http_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_server_missing_resources_bulk_raises(self, server_service):
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = ["r1", "r2"]
        server_in.associated_prompts = []
        server_in.associated_a2a_agents = []

        db.rollback = Mock()
        # Bulk query returns only one resource -> missing set triggers raise at line 553.
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id="r1")]

        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="Failed to register server"):
                await server_service.register_server(db, server_in)

    @pytest.mark.asyncio
    async def test_register_server_missing_resource_single_raises(self, server_service):
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = ["r1"]
        server_in.associated_prompts = []
        server_in.associated_a2a_agents = []

        db.rollback = Mock()
        db.get = Mock(return_value=None)
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="Failed to register server"):
                await server_service.register_server(db, server_in)

    @pytest.mark.asyncio
    async def test_register_server_missing_prompts_bulk_raises(self, server_service):
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = []
        server_in.associated_prompts = ["p1", "p2"]
        server_in.associated_a2a_agents = []

        db.rollback = Mock()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id="p1")]
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="Failed to register server"):
                await server_service.register_server(db, server_in)

    @pytest.mark.asyncio
    async def test_register_server_missing_prompt_single_raises(self, server_service):
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = []
        server_in.associated_prompts = ["p1"]
        server_in.associated_a2a_agents = []

        db.rollback = Mock()
        db.get = Mock(return_value=None)
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="Failed to register server"):
                await server_service.register_server(db, server_in)

    @pytest.mark.asyncio
    async def test_register_server_missing_a2a_agents_bulk_raises(self, server_service):
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = []
        server_in.associated_prompts = []
        server_in.associated_a2a_agents = ["a1", "a2"]

        db.rollback = Mock()
        db.execute.return_value.scalars.return_value.all.return_value = [MagicMock(id="a1")]
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="Failed to register server"):
                await server_service.register_server(db, server_in)

    @pytest.mark.asyncio
    async def test_register_server_a2a_agent_single_success_covers_log_line(self, server_service):
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = []
        server_in.associated_prompts = []
        server_in.associated_a2a_agents = ["a1"]

        agent = MagicMock()
        agent.id = "a1"
        agent.name = "agent1"

        db.rollback = Mock()
        db.get = Mock(return_value=agent)
        db.add = Mock()
        db.commit = Mock()
        db.refresh = Mock()

        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = MagicMock(return_value="server_read")
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            result = await server_service.register_server(db, server_in)
        assert result == "server_read"

    @pytest.mark.asyncio
    async def test_register_server_prompts_bulk_success_executes_extend(self, server_service):
        """Cover bulk prompts association success path (line 572)."""
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = []
        server_in.associated_prompts = ["p1", "p2"]
        server_in.associated_a2a_agents = []

        prompt1 = MagicMock()
        prompt1.id = "p1"
        prompt2 = MagicMock()
        prompt2.id = "p2"
        db.execute.return_value.scalars.return_value.all.return_value = [prompt1, prompt2]
        db.add = Mock()
        db.commit = Mock()
        db.refresh = Mock()

        server_service._notify_server_added = AsyncMock()
        server_service.convert_server_to_read = MagicMock(return_value="server_read")
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            result = await server_service.register_server(db, server_in)

        assert result == "server_read"

    @pytest.mark.asyncio
    async def test_register_server_missing_a2a_agent_single_raises(self, server_service):
        """Cover single A2A agent missing raise (line 600)."""
        db = MagicMock()
        server_in = MagicMock()
        server_in.id = None
        server_in.name = "srv"
        server_in.description = None
        server_in.icon = None
        server_in.tags = []
        server_in.associated_tools = []
        server_in.associated_resources = []
        server_in.associated_prompts = []
        server_in.associated_a2a_agents = ["a1"]

        db.rollback = Mock()
        db.get = Mock(return_value=None)
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerError, match="Failed to register server"):
                await server_service.register_server(db, server_in)

    @pytest.mark.asyncio
    async def test_list_servers_uses_cache_and_reconstructs(self, server_service):
        db = MagicMock()
        mock_cache = AsyncMock()
        mock_cache.hash_filters.return_value = "h"
        mock_cache.get = AsyncMock(return_value={"servers": [{"id": "1"}], "next_cursor": "n"})

        with patch("mcpgateway.services.server_service._get_registry_cache", return_value=mock_cache), patch(
            "mcpgateway.services.server_service.ServerRead.model_validate", return_value="server_read"
        ):
            servers, next_cursor = await server_service.list_servers(db, token_teams=[])

        assert servers == ["server_read"]
        assert next_cursor == "n"

    @pytest.mark.asyncio
    async def test_list_servers_team_scoped_token_user_email_and_visibility_filter(self, server_service):
        db = MagicMock()
        db.commit = Mock()
        with patch("mcpgateway.services.server_service._get_registry_cache", return_value=AsyncMock()), patch(
            "mcpgateway.services.server_service.unified_paginate", new=AsyncMock(return_value=([], None))
        ):
            servers, next_cursor = await server_service.list_servers(
                db,
                token_teams=["t1"],
                user_email="user@example.com",
                visibility="public",
            )

        assert servers == []
        assert next_cursor is None

    @pytest.mark.asyncio
    async def test_list_servers_team_scoped_token_without_user_email_skips_private_condition(self, server_service):
        """Cover token_teams branch where user_email is falsy (807->809)."""
        db = MagicMock()
        db.commit = Mock()
        with patch("mcpgateway.services.server_service._get_registry_cache", return_value=AsyncMock()), patch(
            "mcpgateway.services.server_service.unified_paginate", new=AsyncMock(return_value=([], None))
        ):
            servers, next_cursor = await server_service.list_servers(db, token_teams=["t1"], user_email=None)

        assert servers == []
        assert next_cursor is None

    @pytest.mark.asyncio
    async def test_list_servers_user_email_visibility_filter(self, server_service):
        db = MagicMock()
        db.commit = Mock()
        with patch("mcpgateway.services.server_service._get_registry_cache", return_value=AsyncMock()), patch(
            "mcpgateway.services.server_service.TeamManagementService"
        ) as mock_team_svc, patch(
            "mcpgateway.services.server_service.unified_paginate", new=AsyncMock(return_value=([], None))
        ):
            mock_team_svc.return_value.get_user_teams = AsyncMock(return_value=[])
            servers, next_cursor = await server_service.list_servers(db, user_email="user@example.com", visibility="public")

        assert servers == []
        assert next_cursor is None

    @pytest.mark.asyncio
    async def test_list_servers_caches_first_page_public_only(self, server_service):
        db = MagicMock()
        db.commit = Mock()
        mock_cache = AsyncMock()
        mock_cache.hash_filters.return_value = "h"
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        server_read = MagicMock()
        server_read.model_dump = MagicMock(return_value={"id": "1"})

        with patch("mcpgateway.services.server_service._get_registry_cache", return_value=mock_cache), patch(
            "mcpgateway.services.server_service.unified_paginate", new=AsyncMock(return_value=([MagicMock()], None))
        ):
            server_service.convert_server_to_read = MagicMock(return_value=server_read)
            servers, _ = await server_service.list_servers(db, token_teams=[])

        assert servers == [server_read]
        mock_cache.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_list_servers_for_user_team_ids_condition(self, server_service):
        db = MagicMock()
        db.commit = Mock()
        db.execute.return_value.scalars.return_value.all.return_value = []

        team = MagicMock()
        team.id = "t1"
        with patch("mcpgateway.services.server_service.TeamManagementService") as mock_team_svc:
            mock_team_svc.return_value.get_user_teams = AsyncMock(return_value=[team])
            servers = await server_service.list_servers_for_user(db, user_email="user@example.com")
        assert servers == []

    @pytest.mark.asyncio
    async def test_update_server_permission_denied_raises(self, server_service, mock_server):
        db = MagicMock()
        db.rollback = Mock()
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()
        server_service._notify_server_updated = AsyncMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=mock_server), patch(
            "mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=False)
        ):
            with pytest.raises(ServerError, match="Failed to update server"):
                await server_service.update_server(db, "srv-1", ServerUpdate(description="x"), user_email="user@example.com")

    @pytest.mark.asyncio
    async def test_update_server_name_conflict_team_visibility_raises(self, server_service, mock_server):
        db = MagicMock()
        db.rollback = Mock()
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        existing = MagicMock()
        existing.enabled = True
        existing.id = "srv-other"
        existing.visibility = "team"

        with patch("mcpgateway.services.server_service.get_for_update", side_effect=[mock_server, existing]), patch(
            "mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)
        ):
            with pytest.raises(Exception):
                await server_service.update_server(
                    db,
                    "srv-1",
                    ServerUpdate(name="new-name", visibility="team", team_id="t1"),
                    user_email="user@example.com",
                )

    @pytest.mark.asyncio
    async def test_update_server_team_name_check_no_conflict_continues_then_team_not_found(self, server_service, mock_server):
        """Cover name check branch where existing_server is falsy (1183->1187)."""
        db = MagicMock()
        db.rollback = Mock()
        db.query.return_value.filter.return_value.first.return_value = None  # Team not found
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", side_effect=[mock_server, None]):
            with pytest.raises(ServerError, match="Team team1 not found"):
                await server_service.update_server(
                    db,
                    "srv-1",
                    ServerUpdate(name="new-name", visibility="team", team_id="team1"),
                    user_email="",
                )

    @pytest.mark.asyncio
    async def test_update_server_duplicate_id_raises_server_error(self, server_service, mock_server):
        db = MagicMock()
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()
        db.rollback = Mock()
        db.get = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.server_service.get_for_update", return_value=mock_server), patch(
            "mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=True)
        ):
            with pytest.raises(ServerError, match="Failed to update server"):
                await server_service.update_server(
                    db,
                    "srv-1",
                    ServerUpdate(id="550e8400-e29b-41d4-a716-446655440000"),
                    user_email="user@example.com",
                )

    @pytest.mark.asyncio
    async def test_update_server_team_visibility_without_team_id_raises(self, server_service, mock_server):
        db = MagicMock()
        db.rollback = Mock()
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=mock_server):
            with pytest.raises(ServerError, match="Cannot set visibility"):
                await server_service.update_server(db, "srv-1", ServerUpdate(visibility="team"), user_email="")

    @pytest.mark.asyncio
    async def test_update_server_team_not_found_raises(self, server_service, mock_server):
        db = MagicMock()
        db.rollback = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=mock_server):
            with pytest.raises(ServerError, match="Team team1 not found"):
                await server_service.update_server(db, "srv-1", ServerUpdate(visibility="team", team_id="team1"), user_email="")

    @pytest.mark.asyncio
    async def test_update_server_sets_team_id_and_version_default(self, server_service, mock_server):
        db = MagicMock()
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()
        server_service._notify_server_updated = AsyncMock()
        server_service.convert_server_to_read = MagicMock(return_value="server_read")
        db.commit = Mock()
        db.refresh = Mock()
        db.rollback = Mock()

        # Force version else branch
        mock_server.version = None

        cache = AsyncMock()
        cache.invalidate_servers = AsyncMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=mock_server), patch(
            "mcpgateway.services.server_service._get_registry_cache", return_value=cache
        ), patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache:
            mock_admin_cache.invalidate_tags = AsyncMock()
            result = await server_service.update_server(db, "srv-1", ServerUpdate(team_id="t1"), user_email="")

        assert result == "server_read"
        assert mock_server.team_id == "t1"
        assert mock_server.version == 1

    @pytest.mark.asyncio
    async def test_set_server_state_not_found_reraises(self, server_service):
        db = MagicMock()
        server_service._structured_logger = MagicMock()
        with patch("mcpgateway.services.server_service.get_for_update", return_value=None):
            with pytest.raises(ServerNotFoundError, match="Server not found"):
                await server_service.set_server_state(db, "srv-404", True)

    @pytest.mark.asyncio
    async def test_set_server_state_changes_enabled_and_invalidates_cache(self, server_service, mock_server):
        db = MagicMock()
        mock_server.enabled = False
        db.commit = Mock()
        db.refresh = Mock()
        server_service._notify_server_activated = AsyncMock()
        server_service._notify_server_deactivated = AsyncMock()
        server_service.convert_server_to_read = MagicMock(return_value="server_read")
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        cache = AsyncMock()
        cache.invalidate_servers = AsyncMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=mock_server), patch("mcpgateway.services.server_service._get_registry_cache", return_value=cache):
            result = await server_service.set_server_state(db, "srv-1", True)

        assert result == "server_read"
        assert mock_server.enabled is True

    @pytest.mark.asyncio
    async def test_set_server_state_no_change_skips_update_block(self, server_service, mock_server):
        """Cover branch where server.enabled already matches activate (1494->1536)."""
        db = MagicMock()
        mock_server.enabled = True
        server_service.convert_server_to_read = MagicMock(return_value="server_read")
        server_service._structured_logger = MagicMock()
        server_service._audit_trail = MagicMock()

        with patch("mcpgateway.services.server_service.get_for_update", return_value=mock_server):
            result = await server_service.set_server_state(db, "srv-1", True)

        assert result == "server_read"
