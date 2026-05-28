# -*- coding: utf-8 -*-
# tests/integration/test_gateway_tool_recovery.py
"""Location: ./tests/integration/test_gateway_tool_recovery.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for gateway and tool recovery flow (Bug #4915).

These tests verify that:
1. Gateway and tool reachability states are updated atomically during recovery
2. Negative cache entries for offline tools are invalidated after successful recovery
3. Tools become immediately invokable after gateway recovery
4. Gateway and tools transition online/offline together without divergence windows
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.cache.tool_lookup_cache import ToolLookupCache
from mcpgateway.db import Base, Gateway, Tool
from mcpgateway.main import app
from mcpgateway.schemas import GatewayCreate, ToolRead
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.verify_credentials import require_auth

# Local
from tests.utils.rbac_mocks import MockPermissionService


@pytest.fixture
def test_db_session():
    """Create a test database session with proper schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Create schema
    Base.metadata.create_all(bind=engine)

    session = TestSessionLocal()
    yield session

    session.close()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def test_client(test_db_session):
    """FastAPI TestClient with test database and auth overrides."""
    from _pytest.monkeypatch import MonkeyPatch
    from mcpgateway.auth import get_current_user
    from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_permission_service
    from mcpgateway.middleware.rbac import get_db as rbac_get_db

    mp = MonkeyPatch()

    # Mock user
    mock_user = MagicMock()
    mock_user.email = "test@example.com"
    mock_user.full_name = "Test User"
    mock_user.is_admin = True
    mock_user.is_active = True

    async def mock_user_with_permissions():
        yield {
            "email": "test@example.com",
            "full_name": "Test User",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
            "db": test_db_session,
        }

    def mock_get_permission_service(*args, **kwargs):
        return MockPermissionService(always_grant=True)

    def override_get_db():
        yield test_db_session

    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        app.dependency_overrides[require_auth] = lambda: "test@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = override_get_db

        client = TestClient(app)
        yield client

        # Cleanup
        app.dependency_overrides.clear()

    mp.undo()


@pytest.fixture
def mock_tool_lookup_cache():
    """Mock tool lookup cache for testing cache invalidation."""
    cache = AsyncMock(spec=ToolLookupCache)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.set_negative = AsyncMock()
    cache.invalidate = AsyncMock()
    cache.invalidate_gateway = AsyncMock()
    return cache


@pytest.fixture
def gateway_service(test_db_session, mock_tool_lookup_cache):
    """Gateway service with mocked cache."""
    service = GatewayService()
    with patch("mcpgateway.services.gateway_service._get_tool_lookup_cache", return_value=mock_tool_lookup_cache):
        yield service


class TestGatewayToolRecoveryIntegration:
    """Integration tests for gateway and tool recovery flow."""

    @pytest.mark.asyncio
    async def test_gateway_and_tools_recover_atomically(self, test_db_session, gateway_service, mock_tool_lookup_cache):
        """Test that gateway and tools transition to reachable atomically.

        This verifies Bug #4915 Part 2: Gateway/tool reachability consistency.
        """
        # Create a gateway with tools in unreachable state
        gateway = Gateway(
            id="gw-test-1",
            name="Test Gateway",
            url="http://test.example.com",
            transport="SSE",
            capabilities={},  # Required field
            enabled=True,
            reachable=False,  # Start offline
            owner_email="test@example.com",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add(gateway)
        test_db_session.flush()

        # Add tools that are also unreachable
        tool1 = Tool(
            id="tool-1",
            name="test-tool-1",
            original_name="test-tool-1",
            description="Test tool 1",
            original_description="Test tool 1",
            input_schema={},  # Required field
            gateway_id=gateway.id,
            enabled=True,
            reachable=False,  # Start offline
            created_via="manual",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        tool2 = Tool(
            id="tool-2",
            name="test-tool-2",
            original_name="test-tool-2",
            description="Test tool 2",
            original_description="Test tool 2",
            input_schema={},  # Required field
            gateway_id=gateway.id,
            enabled=True,
            reachable=False,  # Start offline
            created_via="manual",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add_all([tool1, tool2])
        test_db_session.commit()

        # Verify initial state
        assert gateway.reachable is False
        assert tool1.reachable is False
        assert tool2.reachable is False

        # Simulate gateway recovery via set_gateway_state
        with patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init:
            # Mock successful initialization returning the same tools
            # Create mock tools with proper attributes
            # Use a simple object to avoid MagicMock attribute access issues
            class MockTool:
                def __init__(self, name, description):
                    self.name = name
                    self.description = description
                    self.inputSchema = {}
                    self.input_schema = {}  # Both camelCase and snake_case
                    self.headers = None
                    self.output_schema = None
                    self.jsonpath_filter = ""  # Default from Tool model
                    self.request_type = "SSE"  # Default from Tool model

            mock_tool1 = MockTool("test-tool-1", "Test tool 1")
            mock_tool2 = MockTool("test-tool-2", "Test tool 2")

            mock_init.return_value = (
                {},  # capabilities
                [mock_tool1, mock_tool2],  # tools
                [],  # resources
                [],  # prompts
                [],  # sampling
            )

            # Trigger recovery
            await gateway_service.set_gateway_state(
                db=test_db_session,
                gateway_id=gateway.id,
                activate=True,
                reachable=True,
                only_update_reachable=False,
            )

        # Refresh from DB to get latest state
        test_db_session.expire_all()
        gateway = test_db_session.get(Gateway, gateway.id)
        tool1 = test_db_session.get(Tool, tool1.id)
        tool2 = test_db_session.get(Tool, tool2.id)

        # Verify atomic recovery: gateway and all tools are now reachable
        assert gateway.reachable is True, "Gateway should be reachable after recovery"
        assert tool1.reachable is True, "Tool 1 should be reachable after gateway recovery"
        assert tool2.reachable is True, "Tool 2 should be reachable after gateway recovery"

        # Verify no divergence window: all state changes committed together
        # (This is ensured by the fix in set_gateway_state that performs tool bulk update before commit)

    @pytest.mark.asyncio
    async def test_negative_cache_invalidated_on_recovery(self, test_db_session, gateway_service, mock_tool_lookup_cache):
        """Test that negative cache entries are invalidated when tools recover.

        This verifies Bug #4915 Part 1: Negative cache survival.
        """
        # Create a gateway with a tool
        gateway = Gateway(
            id="gw-test-2",
            name="Test Gateway 2",
            url="http://test2.example.com",
            transport="SSE",
            capabilities={},  # Required field
            enabled=True,
            reachable=False,
            owner_email="test@example.com",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add(gateway)
        test_db_session.flush()

        tool = Tool(
            id="tool-3",
            name="test-tool-3",
            original_name="test-tool-3",
            description="Test tool 3",
            original_description="Test tool 3",
            input_schema={},  # Required field
            gateway_id=gateway.id,
            enabled=True,
            reachable=False,
            created_via="manual",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add(tool)
        test_db_session.commit()

        # Simulate negative cache entry for offline tool
        mock_tool_lookup_cache.get.return_value = {"status": "offline", "reason": "gateway unreachable"}

        # Trigger recovery
        with patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init:
            # Create mock tool with proper attributes
            class MockTool:
                def __init__(self, name, description):
                    self.name = name
                    self.description = description
                    self.inputSchema = {}
                    self.input_schema = {}
                    self.headers = None
                    self.output_schema = None
                    self.jsonpath_filter = ""
                    self.request_type = "SSE"

            mock_tool = MockTool("test-tool-3", "Test tool 3")

            mock_init.return_value = (
                {},
                [mock_tool],
                [],
                [],
                [],
            )

            await gateway_service.set_gateway_state(
                db=test_db_session,
                gateway_id=gateway.id,
                activate=True,
                reachable=True,
                only_update_reachable=False,
            )

        # Verify cache invalidation was called for the recovered tool
        # The fix in _update_or_create_tools should call invalidate() for restored tools
        mock_tool_lookup_cache.invalidate.assert_called()

        # Verify the tool name was invalidated
        invalidate_calls = [call[0][0] for call in mock_tool_lookup_cache.invalidate.call_args_list]
        assert "test-tool-3" in invalidate_calls, "Tool cache should be invalidated by name"

    @pytest.mark.asyncio
    async def test_tools_immediately_invokable_after_recovery(self, test_db_session, gateway_service, mock_tool_lookup_cache):
        """Test that tools become immediately invokable after gateway recovery.

        This is the user-facing verification of the fix.
        """
        # Create gateway and tool in offline state
        gateway = Gateway(
            id="gw-test-3",
            name="Test Gateway 3",
            url="http://test3.example.com",
            transport="SSE",
            capabilities={},  # Required field
            enabled=True,
            reachable=False,
            owner_email="test@example.com",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add(gateway)
        test_db_session.flush()

        tool = Tool(
            id="tool-4",
            name="test-tool-4",
            original_name="test-tool-4",
            description="Test tool 4",
            original_description="Test tool 4",
            input_schema={},  # Required field
            gateway_id=gateway.id,
            enabled=True,
            reachable=False,
            created_via="manual",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add(tool)
        test_db_session.commit()

        # Trigger recovery
        with patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init:
            # Create mock tool with proper attributes
            class MockTool:
                def __init__(self, name, description):
                    self.name = name
                    self.description = description
                    self.inputSchema = {}
                    self.input_schema = {}
                    self.headers = None
                    self.output_schema = None
                    self.jsonpath_filter = ""
                    self.request_type = "SSE"

            mock_tool = MockTool("test-tool-4", "Test tool 4")

            mock_init.return_value = (
                {},
                [mock_tool],
                [],
                [],
                [],
            )

            await gateway_service.set_gateway_state(
                db=test_db_session,
                gateway_id=gateway.id,
                activate=True,
                reachable=True,
                only_update_reachable=False,
            )

        # Refresh and verify tool is reachable
        test_db_session.expire_all()
        tool = test_db_session.get(Tool, tool.id)
        assert tool.reachable is True, "Tool should be reachable immediately after recovery"

        # Verify cache was invalidated (no stale offline entry)
        assert mock_tool_lookup_cache.invalidate.called, "Cache should be invalidated for recovered tool"

    @pytest.mark.asyncio
    async def test_health_check_recovery_flow(self, test_db_session, gateway_service, mock_tool_lookup_cache):
        """Test the complete health check recovery flow.

        This simulates the actual health check path that triggers recovery.
        """
        # Create gateway and tools in offline state
        gateway = Gateway(
            id="gw-test-4",
            name="Test Gateway 4",
            url="http://test4.example.com",
            transport="SSE",
            capabilities={},  # Required field
            enabled=True,
            reachable=False,
            owner_email="test@example.com",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add(gateway)
        test_db_session.flush()

        tools = [
            Tool(
                id=f"tool-{i}",
                name=f"test-tool-{i}",
                original_name=f"test-tool-{i}",
                description=f"Test tool {i}",
                original_description=f"Test tool {i}",
                input_schema={},  # Required field
                gateway_id=gateway.id,
                enabled=True,
                reachable=False,
                created_via="health_check",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            for i in range(5, 8)
        ]
        test_db_session.add_all(tools)
        test_db_session.commit()

        # Simulate health check recovery
        with patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init:
            # Create mock tools with proper attributes
            class MockTool:
                def __init__(self, name, description):
                    self.name = name
                    self.description = description
                    self.inputSchema = {}
                    self.input_schema = {}
                    self.headers = None
                    self.output_schema = None
                    self.jsonpath_filter = ""
                    self.request_type = "SSE"

            mock_tools = []
            for i in range(5, 8):
                mock_tools.append(MockTool(f"test-tool-{i}", f"Test tool {i}"))

            mock_init.return_value = (
                {},
                mock_tools,
                [],
                [],
                [],
            )

            # This simulates the health check calling set_gateway_state
            await gateway_service.set_gateway_state(
                db=test_db_session,
                gateway_id=gateway.id,
                activate=True,
                reachable=True,
                only_update_reachable=True,  # Health check uses this flag
            )

        # Verify all tools recovered atomically with gateway
        test_db_session.expire_all()
        gateway = test_db_session.get(Gateway, gateway.id)
        assert gateway.reachable is True

        for i in range(5, 8):
            tool = test_db_session.get(Tool, f"tool-{i}")
            assert tool.reachable is True, f"Tool {i} should be reachable after health check recovery"

        # Verify cache invalidation for all recovered tools
        assert mock_tool_lookup_cache.invalidate.call_count >= 3, "All recovered tools should have cache invalidated"
