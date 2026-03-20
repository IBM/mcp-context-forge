# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_dynamic_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for the dynamic server catalog router.

Covers all 11 REST endpoints:
  - CRUD: create, list, get, update, delete dynamic servers
  - Rules: add rule, delete rule
  - Catalog stubs: tools, resources, prompts, preview (all return 501)
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException, status
import pytest
from sqlalchemy.orm import Session

from mcpgateway.schemas import (
    DynamicRuleCreate,
    DynamicRuleRead,
    DynamicServerCreate,
    DynamicServerRead,
    DynamicServerUpdate,
)

from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


class TestDynamicRouter:
    """Unit tests for mcpgateway.routers.dynamic_router."""

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def setup_rbac_mocks(self):
        """Bypass RBAC decorators for every test."""
        originals = patch_rbac_decorators()
        yield
        restore_rbac_decorators(originals)

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_user_context(self, mock_db):
        """Standard non-admin user context."""
        return {
            "email": "dev@example.com",
            "full_name": "Dev User",
            "is_admin": False,
            "teams": ["team-alpha"],
            "db": mock_db,
            "permissions": [
                "dynamic_servers.create",
                "dynamic_servers.read",
                "dynamic_servers.update",
                "dynamic_servers.delete",
            ],
        }

    @pytest.fixture
    def sample_server_read(self):
        """Return a DynamicServerRead instance for mocking service results."""
        return DynamicServerRead(
            id=str(uuid4()),
            name="my-dynamic-server",
            description="A test dynamic server",
            rules=[],
            refresh_interval=60,
            visibility="team",
            created_at=datetime.now(timezone.utc),
            created_by="dev@example.com",
        )

    @pytest.fixture
    def sample_rule_read(self):
        """Return a DynamicRuleRead instance for mocking rule results."""
        return DynamicRuleRead(
            id=str(uuid4()),
            rule_type="tag",
            entity_type="tool",
            value="search",
            created_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # 1. POST / — create_dynamic_server
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_dynamic_server(self, mock_user_context, mock_db, sample_server_read):
        """Test creating a dynamic server returns 201 and the created server."""
        request = DynamicServerCreate(
            name="my-dynamic-server",
            description="A test dynamic server",
            rules=[],
            refresh_interval=60,
            visibility="team",
        )

        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.create_dynamic_server.return_value = sample_server_read
            mock_svc_cls.return_value = mock_service

            from mcpgateway.routers.dynamic_router import create_dynamic_server

            result = await create_dynamic_server(
                request=request,
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

            assert result.name == "my-dynamic-server"
            mock_service.create_dynamic_server.assert_called_once_with(mock_db, request, mock_user_context)

    # ------------------------------------------------------------------
    # 2. GET / — list_dynamic_servers
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_dynamic_servers(self, mock_user_context, mock_db, sample_server_read):
        """Test listing dynamic servers respects pagination and team scoping."""
        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.list_dynamic_servers.return_value = [sample_server_read]
            mock_svc_cls.return_value = mock_service

            from mcpgateway.routers.dynamic_router import list_dynamic_servers

            result = await list_dynamic_servers(
                limit=10,
                offset=5,
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

            assert len(result) == 1
            assert result[0].name == "my-dynamic-server"
            mock_service.list_dynamic_servers.assert_called_once_with(
                mock_db,
                token_teams=["team-alpha"],
                limit=10,
                offset=5,
            )

    # ------------------------------------------------------------------
    # 3. GET /{server_id} — get_dynamic_server (success)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_dynamic_server(self, mock_user_context, mock_db, sample_server_read):
        """Test fetching a dynamic server by ID returns the server."""
        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.get_dynamic_server.return_value = sample_server_read
            mock_svc_cls.return_value = mock_service

            from mcpgateway.routers.dynamic_router import get_dynamic_server

            result = await get_dynamic_server(
                server_id=sample_server_read.id,
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

            assert result.id == sample_server_read.id
            mock_service.get_dynamic_server.assert_called_once_with(mock_db, sample_server_read.id)

    # ------------------------------------------------------------------
    # 4. GET /{server_id} — get_dynamic_server (404)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_dynamic_server_not_found(self, mock_user_context, mock_db):
        """Test that a missing server returns HTTP 404."""
        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.get_dynamic_server.side_effect = HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dynamic server not found",
            )
            mock_svc_cls.return_value = mock_service

            from mcpgateway.routers.dynamic_router import get_dynamic_server

            with pytest.raises(HTTPException) as exc_info:
                await get_dynamic_server(
                    server_id="nonexistent-id",
                    current_user_ctx=mock_user_context,
                    db=mock_db,
                )

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    # ------------------------------------------------------------------
    # 5. PUT /{server_id} — update_dynamic_server
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_update_dynamic_server(self, mock_user_context, mock_db, sample_server_read):
        """Test updating a dynamic server returns the updated record."""
        request = DynamicServerUpdate(description="Updated description")

        updated = sample_server_read.model_copy(update={"description": "Updated description"})

        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.update_dynamic_server.return_value = updated
            mock_svc_cls.return_value = mock_service

            from mcpgateway.routers.dynamic_router import update_dynamic_server

            result = await update_dynamic_server(
                server_id=sample_server_read.id,
                request=request,
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

            assert result.description == "Updated description"
            mock_service.update_dynamic_server.assert_called_once_with(mock_db, sample_server_read.id, request)

    # ------------------------------------------------------------------
    # 6. DELETE /{server_id} — delete_dynamic_server
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_dynamic_server(self, mock_user_context, mock_db):
        """Test deleting a dynamic server returns None (HTTP 204)."""
        server_id = str(uuid4())

        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.delete_dynamic_server.return_value = None
            mock_svc_cls.return_value = mock_service

            from mcpgateway.routers.dynamic_router import delete_dynamic_server

            result = await delete_dynamic_server(
                server_id=server_id,
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

            assert result is None
            mock_service.delete_dynamic_server.assert_called_once_with(mock_db, server_id)

    # ------------------------------------------------------------------
    # 7. POST /{server_id}/rules — add_rule
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_add_rule(self, mock_user_context, mock_db):
        """Test adding a rule to a dynamic server returns 201 and the new rule."""
        server_id = str(uuid4())
        rule_id = str(uuid4())
        now = datetime.now(timezone.utc)

        request = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="search")

        # Mock service.get_dynamic_server so the server-exists check passes
        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.get_dynamic_server.return_value = MagicMock()  # exists
            mock_svc_cls.return_value = mock_service

            # Mock the DbDynamicRule constructor — the router creates the ORM object
            with patch("mcpgateway.routers.dynamic_router.DbDynamicRule") as mock_rule_cls:
                mock_rule_instance = MagicMock()
                mock_rule_instance.id = rule_id
                mock_rule_instance.rule_type = "tag"
                mock_rule_instance.entity_type = "tool"
                mock_rule_instance.value = "search"
                mock_rule_instance.created_at = now
                mock_rule_cls.return_value = mock_rule_instance

                from mcpgateway.routers.dynamic_router import add_rule

                result = await add_rule(
                    server_id=server_id,
                    request=request,
                    current_user_ctx=mock_user_context,
                    db=mock_db,
                )

                assert isinstance(result, DynamicRuleRead)
                assert result.id == rule_id
                assert result.rule_type == "tag"
                assert result.entity_type == "tool"
                assert result.value == "search"
                mock_db.add.assert_called_once_with(mock_rule_instance)
                mock_db.commit.assert_called_once()
                mock_db.refresh.assert_called_once_with(mock_rule_instance)

    # ------------------------------------------------------------------
    # 8. DELETE /{server_id}/rules/{rule_id} — delete_rule
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_rule(self, mock_user_context, mock_db):
        """Test deleting a rule returns None (HTTP 204)."""
        server_id = str(uuid4())
        rule_id = str(uuid4())

        # Mock service.get_dynamic_server so the server-exists check passes
        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.get_dynamic_server.return_value = MagicMock()  # exists
            mock_svc_cls.return_value = mock_service

            # Mock db.get(DbDynamicRule, rule_id) to return a matching rule
            mock_rule = MagicMock()
            mock_rule.dynamic_server_id = server_id
            mock_db.get.return_value = mock_rule

            from mcpgateway.routers.dynamic_router import delete_rule

            result = await delete_rule(
                server_id=server_id,
                rule_id=rule_id,
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

            assert result is None
            mock_db.delete.assert_called_once_with(mock_rule)
            mock_db.commit.assert_called_once()

    # ------------------------------------------------------------------
    # 9. DELETE /{server_id}/rules/{rule_id} — delete_rule (404)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_rule_not_found(self, mock_user_context, mock_db):
        """Test deleting a non-existent rule returns 404."""
        server_id = str(uuid4())
        rule_id = str(uuid4())

        with patch("mcpgateway.routers.dynamic_router.DynamicServerService") as mock_svc_cls:
            mock_service = MagicMock()
            mock_service.get_dynamic_server.return_value = MagicMock()
            mock_svc_cls.return_value = mock_service

            mock_db.get.return_value = None  # rule not found

            from mcpgateway.routers.dynamic_router import delete_rule

            with pytest.raises(HTTPException) as exc_info:
                await delete_rule(
                    server_id=server_id,
                    rule_id=rule_id,
                    current_user_ctx=mock_user_context,
                    db=mock_db,
                )

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    # ------------------------------------------------------------------
    # 10–13. Catalog Stubs — all return 501
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_catalog_tools_stub_returns_501(self, mock_user_context, mock_db):
        """Test that the catalog tools endpoint returns HTTP 501."""
        from mcpgateway.routers.dynamic_router import get_catalog_tools

        with pytest.raises(HTTPException) as exc_info:
            await get_catalog_tools(
                server_id=str(uuid4()),
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

        assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_get_catalog_resources_stub_returns_501(self, mock_user_context, mock_db):
        """Test that the catalog resources endpoint returns HTTP 501."""
        from mcpgateway.routers.dynamic_router import get_catalog_resources

        with pytest.raises(HTTPException) as exc_info:
            await get_catalog_resources(
                server_id=str(uuid4()),
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

        assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_get_catalog_prompts_stub_returns_501(self, mock_user_context, mock_db):
        """Test that the catalog prompts endpoint returns HTTP 501."""
        from mcpgateway.routers.dynamic_router import get_catalog_prompts

        with pytest.raises(HTTPException) as exc_info:
            await get_catalog_prompts(
                server_id=str(uuid4()),
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

        assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_preview_catalog_stub_returns_501(self, mock_user_context, mock_db):
        """Test that the catalog preview endpoint returns HTTP 501."""
        from mcpgateway.routers.dynamic_router import preview_catalog

        request = DynamicServerCreate(
            name="preview-test",
            rules=[],
        )

        with pytest.raises(HTTPException) as exc_info:
            await preview_catalog(
                request=request,
                current_user_ctx=mock_user_context,
                db=mock_db,
            )

        assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED
