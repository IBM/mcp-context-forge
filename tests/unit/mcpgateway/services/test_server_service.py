# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for server service implementation.
"""

# Standard
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
    server.visibility = "public"

    # Associated objects -------------------------------------------------- #
    server.tools = [mock_tool]
    server.resources = [mock_resource]
    server.prompts = [mock_prompt]

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
        test_db.execute = Mock()
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
        test_db.execute = Mock()
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
        test_db.execute = Mock()
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
        server_service._convert_server_to_read = Mock(
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
            # Set up the mock server to be returned later
            server.id = 1
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

        # Stub helper that converts to the public schema
        server_service._notify_server_added = AsyncMock()
        server_service._convert_server_to_read = Mock(
            return_value=ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
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
        server_service._convert_server_to_read = Mock(return_value=server_read)

        result = await server_service.list_servers(test_db)

        # test_db.execute.assert_called_once()
        test_db.execute.call_count = 2
        assert result == [server_read]
        server_service._convert_server_to_read.assert_called_once_with(mock_server, include_metrics=False)

    @pytest.mark.asyncio
    async def test_get_server(self, server_service, mock_server, test_db):
        mock_server.team_id = 1
        test_db.get = MagicMock(return_value=mock_server)

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
        server_service._convert_server_to_read = Mock(return_value=server_read)

        result = await server_service.get_server(test_db, 1)

        test_db.get.assert_called_once_with(DbServer, 1)
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

        # db.get is still used to retrieve the Server itself
        test_db.get = Mock(
            side_effect=lambda cls, _id: (
                mock_server
                if (cls, _id) == (DbServer, 1)
                else None
            )
        )

        # FIX: Configure db.execute to handle both the conflict check and the bulk item fetches
        mock_db_result = MagicMock()

        # 1. Handle name conflict check: scalar_one_or_none() -> None
        mock_db_result.scalar_one_or_none.return_value = None

        # 2. Handle bulk fetches: scalars().all() -> lists of items
        # The code executes bulk queries in this order: Tools -> Resources -> Prompts
        mock_db_result.scalars.return_value.all.side_effect = [
            [new_tool],      # First call: select(DbTool)...
            [new_resource],  # Second call: select(DbResource)...
            [new_prompt]     # Third call: select(DbPrompt)...
        ]

        test_db.execute = Mock(return_value=mock_db_result)

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
        server_service._convert_server_to_read = Mock(
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
            test_db.execute = Mock(return_value=mock_scalar)
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
            test_db.execute = Mock(return_value=mock_scalar)
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
            test_db.execute = Mock(return_value=mock_scalar)
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

    # -------------------------- toggle --------------------------------- #
    @pytest.mark.asyncio
    async def test_toggle_server_status(self, server_service, mock_server, test_db):
        mock_server.team_id = 1
        test_db.get = Mock(return_value=mock_server)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_activated = AsyncMock()
        server_service._notify_server_deactivated = AsyncMock()
        server_service._convert_server_to_read = Mock(
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

        result = await server_service.toggle_server_status(test_db, 1, activate=False)

        test_db.get.assert_called_once_with(DbServer, 1)
        # commit called twice: once for status change, once in _get_team_name to release transaction
        assert test_db.commit.call_count == 2
        test_db.refresh.assert_called_once()
        server_service._notify_server_deactivated.assert_called_once()
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
        test_db.execute.assert_called_once()
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
        server_service._convert_server_to_read = Mock(
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
        server_service._convert_server_to_read = Mock(
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
        server_service._convert_server_to_read = Mock(
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
        test_db.get = Mock(side_effect=lambda cls, _id: existing_server if _id == "oldserverid" else None)

        # Mock name conflict check
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock service methods
        server_service._notify_server_updated = AsyncMock()
        server_service._convert_server_to_read = Mock(
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
        mock_query.where.return_value = mock_query

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [mock_server]

        bind = MagicMock()
        bind.dialect = MagicMock()
        bind.dialect.name = "sqlite"  # or "postgresql" or "mysql"
        session.get_bind.return_value = bind

        with patch("mcpgateway.services.server_service.select", return_value=mock_query):
            with patch("mcpgateway.services.server_service.json_contains_expr") as mock_json_contains:
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
                # finally, your service should return the list produced by mock_db.execute(...)
                assert isinstance(result, list)
                assert len(result) == 1
