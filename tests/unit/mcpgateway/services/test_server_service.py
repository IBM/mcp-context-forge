# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for server service implementation.
"""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ServerCreate, ServerRead, ServerUpdate
from mcpgateway.services.server_service import (
    ServerError,
    ServerNameConflictError,
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
def mock_server():
    """Return a mocked DbServer object with minimal required attributes."""
    server = MagicMock(spec=DbServer)
    server.id = 1
    server.name = "test_server"
    server.description = "A test server"
    server.icon = "server-icon"
    server.created_at = "2023-01-01T00:00:00"
    server.updated_at = "2023-01-01T00:00:00"
    server.is_active = True

    # Associated objects -------------------------------------------------- #
    tool1 = MagicMock(spec=DbTool)
    tool1.id = 101
    tool1._sa_instance_state = Mock()

    resource1 = MagicMock(spec=DbResource)
    resource1.id = 201
    resource1._sa_instance_state = Mock()

    prompt1 = MagicMock(spec=DbPrompt)
    prompt1.id = 301
    prompt1._sa_instance_state = Mock()

    server.tools = [tool1]
    server.resources = [resource1]
    server.prompts = [prompt1]

    # Dummy metrics
    server.metrics = []
    return server


@pytest.fixture
def mock_tool():
    tool = MagicMock(spec=DbTool)
    tool.id = 101
    tool.name = "test_tool"
    tool._sa_instance_state = Mock()
    return tool


@pytest.fixture
def mock_resource():
    res = MagicMock(spec=DbResource)
    res.id = 201
    res.name = "test_resource"
    res._sa_instance_state = Mock()
    return res


@pytest.fixture
def mock_prompt():
    pr = MagicMock(spec=DbPrompt)
    pr.id = 301
    pr.name = "test_prompt"
    pr._sa_instance_state = Mock()
    return pr


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
class TestServerService:
    """Unit-tests for the ServerService class."""

    # ------------------------- register_server -------------------------- #
    @pytest.mark.asyncio
    async def test_register_server(
        self, server_service, test_db, mock_tool, mock_resource, mock_prompt
    ):
        """Successful registration returns populated ServerRead."""
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Stub db.get to resolve associated items
        test_db.get = Mock(
            side_effect=lambda cls, _id: {
                (DbTool, 101): mock_tool,
                (DbResource, 201): mock_resource,
                (DbPrompt, 301): mock_prompt,
            }.get((cls, _id))
        )

        # Patch conversion helper
        server_service._notify_server_added = AsyncMock()
        server_service._convert_server_to_read = Mock(
            return_value=ServerRead(
                id=1,
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                associated_tools=[101],
                associated_resources=[201],
                associated_prompts=[301],
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
            icon="server-icon",
            associated_tools=["101"],
            associated_resources=["201"],
            associated_prompts=["301"],
        )

        result = await server_service.register_server(test_db, server_create)

        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        server_service._notify_server_added.assert_called_once()

        assert result.name == "test_server"
        assert 101 in result.associated_tools
        assert 201 in result.associated_resources
        assert 301 in result.associated_prompts

    @pytest.mark.asyncio
    async def test_register_server_name_conflict(self, server_service, mock_server, test_db):
        """Server name clash is surfaced as ServerError (wrapped by service)."""
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_server
        test_db.execute = Mock(return_value=mock_scalar)

        server_create = ServerCreate(
            name="test_server",
            description="A new server",
            icon="new-icon",
        )

        with pytest.raises(ServerError) as exc:
            await server_service.register_server(test_db, server_create)

        assert "Server already exists with name" in str(exc.value)

    @pytest.mark.asyncio
    async def test_register_server_invalid_associated_tool(self, server_service, test_db):
        """Non-existent associated tool raises ServerError."""
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

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
        exec_result.scalars.return_value.all.return_value = [mock_server]
        test_db.execute = Mock(return_value=exec_result)

        server_read = ServerRead(
            id=1,
            name="test_server",
            description="A test server",
            icon="server-icon",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            is_active=True,
            associated_tools=[101],
            associated_resources=[201],
            associated_prompts=[301],
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

        test_db.execute.assert_called_once()
        assert result == [server_read]
        server_service._convert_server_to_read.assert_called_once_with(mock_server)

    @pytest.mark.asyncio
    async def test_get_server(self, server_service, mock_server, test_db):
        test_db.get = Mock(return_value=mock_server)

        server_read = ServerRead(
            id=1,
            name="test_server",
            description="A test server",
            icon="server-icon",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            is_active=True,
            associated_tools=[101],
            associated_resources=[201],
            associated_prompts=[301],
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
    async def test_update_server(
        self, server_service, mock_server, test_db, mock_tool, mock_resource, mock_prompt
    ):
        test_db.get = Mock(
            side_effect=lambda cls, _id: (
                mock_server
                if (cls, _id) == (DbServer, 1)
                else {
                    (DbTool, 102): mock_tool,
                    (DbResource, 202): mock_resource,
                    (DbPrompt, 302): mock_prompt,
                }.get((cls, _id))
            )
        )

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_updated = AsyncMock()
        server_service._convert_server_to_read = Mock(
            return_value=ServerRead(
                id=1,
                name="updated_server",
                description="An updated server",
                icon="updated-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                associated_tools=[102],
                associated_resources=[202],
                associated_prompts=[302],
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
            icon="updated-icon",
            associated_tools=["102"],
            associated_resources=["202"],
            associated_prompts=["302"],
        )

        result = await server_service.update_server(test_db, 1, server_update)

        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        server_service._notify_server_updated.assert_called_once()
        assert result.name == "updated_server"

    @pytest.mark.asyncio
    async def test_update_server_not_found(self, server_service, test_db):
        test_db.get = Mock(return_value=None)
        update_data = ServerUpdate(name="updated_server")
        with pytest.raises(ServerError) as exc:
            await server_service.update_server(test_db, 999, update_data)
        assert "Server not found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_update_server_name_conflict(self, server_service, mock_server, test_db):
        server1 = mock_server
        server2 = MagicMock(spec=DbServer)
        server2.id = 2
        server2.name = "existing_server"
        server2.is_active = True

        test_db.get = Mock(return_value=server1)
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = server2
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.rollback = Mock()

        with pytest.raises(ServerError) as exc:
            await server_service.update_server(
                test_db,
                1,
                ServerUpdate(name="existing_server"),
            )
        assert "Server already exists with name" in str(exc.value)

    # -------------------------- toggle --------------------------------- #
    @pytest.mark.asyncio
    async def test_toggle_server_status(self, server_service, mock_server, test_db):
        test_db.get = Mock(return_value=mock_server)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        server_service._notify_server_activated = AsyncMock()
        server_service._notify_server_deactivated = AsyncMock()
        server_service._convert_server_to_read = Mock(
            return_value=ServerRead(
                id=1,
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=False,
                associated_tools=[101],
                associated_resources=[201],
                associated_prompts=[301],
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
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        server_service._notify_server_deactivated.assert_called_once()
        assert result.is_active is False

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
