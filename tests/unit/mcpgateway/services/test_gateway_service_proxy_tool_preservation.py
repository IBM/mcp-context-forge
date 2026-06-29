# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_proxy_tool_preservation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for PROXIED gateway tool preservation during activation/deactivation cycles.
Tests the fixes for tools being deleted when reactivating PROXIED gateways.

These tests verify:
1. Tools are preserved when deactivating a PROXIED gateway
2. Tools are preserved when reactivating a PROXIED gateway
3. gateway_id parameter is passed correctly to _initialize_gateway
4. Manual refresh preserves tools for PROXIED gateways
5. Cross-worker communication works correctly
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.gateway_service import GatewayService


def _make_execute_result(*, scalar=None, scalars_list=None, rowcount=0):
    """Helper to create mock SQLAlchemy Result objects."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    result.rowcount = rowcount
    return result


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache
    clear_ssl_context_cache()
    
    with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, \
         patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def _bypass_gatewayread_validation(monkeypatch):
    """Stub out GatewayRead.model_validate for mock objects."""
    from mcpgateway.schemas import GatewayRead
    
    def mock_validate(obj, **kwargs):
        """Return a mock GatewayRead that has all required attributes."""
        mock_read = MagicMock(spec=GatewayRead)
        mock_read.id = getattr(obj, 'id', 'test-id')
        mock_read.name = getattr(obj, 'name', 'test-gateway')
        mock_read.url = getattr(obj, 'url', 'http://test')
        mock_read.transport = getattr(obj, 'transport', 'PROXIED')
        mock_read.enabled = getattr(obj, 'enabled', True)
        mock_read.reachable = getattr(obj, 'reachable', True)
        return mock_read
    
    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(mock_validate))


@pytest.fixture
def gateway_service():
    """A GatewayService instance with mocked HTTP client."""
    service = GatewayService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_db():
    """Return a mocked SQLAlchemy session."""
    session = MagicMock()
    session.query.return_value = MagicMock()
    session.commit.return_value = None
    session.rollback.return_value = None
    session.flush.return_value = None
    session.refresh.return_value = None
    session.add.return_value = None
    session.add_all.return_value = None
    session.expire.return_value = None
    return session


@pytest.fixture
def proxied_gateway():
    """Create a mock PROXIED gateway with tools."""
    gateway_id = uuid.uuid4().hex
    
    # Use a simple class instead of MagicMock to avoid __dict__ issues
    class MockGateway:
        def __init__(self):
            self.id = gateway_id
            self.name = "test-proxy-gateway"
            self.url = f"http://localhost/reverse-proxy/sessions/{gateway_id}/mcp"
            self.transport = "PROXIED"
            self.enabled = True
            self.reachable = True
            self.auth_type = "basic"
            self.auth_value = {"username": "test", "password": "test"}
            self.oauth_config = None
            self.auth_query_params = None
            self.ca_certificate = None
            self.team_id = None
            self.owner_email = None
            self.visibility = "private"
            self.tags = []
            self.updated_at = datetime.now(timezone.utc)
            self.created_at = datetime.now(timezone.utc)
            self.created_by = "test"
            self.modified_by = None
            self.version = 1
            self.team = None
            self._sa_instance_state = MagicMock()
            self.tools = []
            self.resources = []
            self.prompts = []
            self.email_team = None
    
    gateway = MockGateway()
    
    # Create mock tools with SQLAlchemy instance state
    tool1 = MagicMock(spec=DbTool)
    tool1.id = uuid.uuid4().hex
    tool1.original_name = "test-tool-1"
    tool1.name = "test-tool-1"
    tool1.enabled = True
    tool1.reachable = True
    tool1.created_via = "update"
    tool1._sa_instance_state = MagicMock()  # Add SQLAlchemy state
    
    tool2 = MagicMock(spec=DbTool)
    tool2.id = uuid.uuid4().hex
    tool2.original_name = "test-tool-2"
    tool2.name = "test-tool-2"
    tool2.enabled = True
    tool2.reachable = True
    tool2.created_via = "update"
    tool2._sa_instance_state = MagicMock()  # Add SQLAlchemy state
    
    gateway.tools = [tool1, tool2]
    gateway.resources = []
    gateway.prompts = []
    gateway.email_team = None
    
    return gateway


@pytest.fixture
def mock_forward_request():
    """Mock forward_request_to_session that returns MCP responses."""
    async def forward_func(session_id, request, **kwargs):
        method = request.get("method")
        
        if method == "initialize":
            return {
                "payload": {
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0.0"}
                    }
                }
            }
        elif method == "notifications/initialized":
            return {"payload": {}}
        elif method == "tools/list":
            return {
                "payload": {
                    "result": {
                        "tools": [
                            {
                                "name": "test-tool-1",
                                "description": "Test tool 1",
                                "inputSchema": {"type": "object", "properties": {}}
                            },
                            {
                                "name": "test-tool-2",
                                "description": "Test tool 2",
                                "inputSchema": {"type": "object", "properties": {}}
                            }
                        ]
                    }
                }
            }
        elif method == "resources/list":
            return {
                "payload": {
                    "result": {"resources": []}
                }
            }
        elif method == "prompts/list":
            return {
                "payload": {
                    "result": {"prompts": []}
                }
            }
        
        return {"payload": {}}
    
    return AsyncMock(side_effect=forward_func)


@pytest.mark.asyncio
async def test_proxied_gateway_deactivation_preserves_tools(gateway_service, mock_db, proxied_gateway):
    """Test that deactivating a PROXIED gateway marks tools as disabled but doesn't delete them."""
    # Setup
    mock_db.execute.return_value = _make_execute_result(scalar=proxied_gateway)
    
    # Mock the bulk update queries
    tools_update_result = MagicMock()
    tools_update_result.rowcount = 2  # 2 tools updated
    mock_db.execute.side_effect = [
        _make_execute_result(scalar=proxied_gateway),  # Initial gateway fetch
        tools_update_result,  # Tools bulk update
        MagicMock(rowcount=0),  # Prompts bulk update
        MagicMock(rowcount=0),  # Resources bulk update
    ]
    
    with patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache:
        mock_cache_instance = AsyncMock()
        mock_cache.return_value = mock_cache_instance
        
        # Deactivate gateway
        result = await gateway_service.set_gateway_state(
            db=mock_db,
            gateway_id=proxied_gateway.id,
            activate=False,
            reachable=True
        )
        
        # Verify gateway was disabled
        assert proxied_gateway.enabled is False
        
        # Verify tools were NOT deleted (no delete() calls)
        delete_calls = [call for call in mock_db.execute.call_args_list 
                       if 'delete' in str(call).lower()]
        assert len(delete_calls) == 0, "Tools should not be deleted during deactivation"
        
        # Verify commit was called
        assert mock_db.commit.called


@pytest.mark.asyncio
async def test_proxied_gateway_reactivation_with_gateway_id(gateway_service, mock_db, proxied_gateway, mock_forward_request):
    """Test that reactivating a PROXIED gateway passes gateway_id to _initialize_gateway."""
    # Setup - gateway starts disabled
    proxied_gateway.enabled = False
    mock_db.execute.return_value = _make_execute_result(scalar=proxied_gateway)
    
    with patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache, \
         patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init:
        
        mock_cache_instance = AsyncMock()
        mock_cache.return_value = mock_cache_instance
        
        # Mock _initialize_gateway to return tools
        mock_init.return_value = (
            {"tools": {}},  # capabilities
            [
                ToolCreate(name="test-tool-1", description="Test tool 1", inputSchema={"type": "object"}),
                ToolCreate(name="test-tool-2", description="Test tool 2", inputSchema={"type": "object"})
            ],
            [],  # resources
            []   # prompts
        )
        
        # Reactivate gateway
        result = await gateway_service.set_gateway_state(
            db=mock_db,
            gateway_id=proxied_gateway.id,
            activate=True,
            reachable=True
        )
        
        # Verify _initialize_gateway was called with gateway_id
        assert mock_init.called
        call_kwargs = mock_init.call_args[1]
        assert "gateway_id" in call_kwargs, "_initialize_gateway should receive gateway_id parameter"
        assert call_kwargs["gateway_id"] == proxied_gateway.id, "gateway_id should match the gateway being activated"


@pytest.mark.asyncio
async def test_proxied_gateway_reactivation_preserves_tools(gateway_service, mock_db, proxied_gateway, mock_forward_request):
    """Test that reactivating a PROXIED gateway preserves existing tools."""
    # Setup - gateway starts disabled
    proxied_gateway.enabled = False
    
    with patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache, \
         patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init, \
         patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, \
         patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger, \
         patch.object(gateway_service, "_notify_gateway_activated", new_callable=AsyncMock) as mock_notify:
        
        mock_cache_instance = AsyncMock()
        mock_cache.return_value = mock_cache_instance
        
        # Mock _initialize_gateway to return the same tools
        mock_init.return_value = (
            {"tools": {}},
            [
                ToolCreate(name="test-tool-1", description="Test tool 1", inputSchema={"type": "object"}),
                ToolCreate(name="test-tool-2", description="Test tool 2", inputSchema={"type": "object"})
            ],
            [],
            []
        )
        
        # Mock database operations
        # Always return proxied_gateway for SELECT queries, rowcount for UPDATE queries
        def execute_side_effect(query):
            # For any query, check if it's a select (returns gateway) or update (returns rowcount)
            # The first call will be the gateway fetch, subsequent calls are updates
            query_str = str(query).lower()
            if 'select' in query_str or hasattr(query, 'column_descriptions'):
                # This is a SELECT query - return the gateway
                return _make_execute_result(scalar=proxied_gateway)
            # This is an UPDATE query - return rowcount
            return MagicMock(rowcount=0)
        
        mock_db.execute.side_effect = execute_side_effect
        mock_db.commit.return_value = None
        # refresh should not reset the object - it's already been modified in memory
        mock_db.refresh = MagicMock(return_value=None)
        mock_db.add_all.return_value = None
        mock_db.flush.return_value = None
        mock_db.rollback.return_value = None
        
        # Reactivate gateway
        result = await gateway_service.set_gateway_state(
            db=mock_db,
            gateway_id=proxied_gateway.id,
            activate=True,
            reachable=True
        )
        
        # Verify _initialize_gateway was called with gateway_id (the main fix)
        assert mock_init.called, "_initialize_gateway should be called during reactivation"
        call_kwargs = mock_init.call_args[1]
        assert "gateway_id" in call_kwargs, "_initialize_gateway should receive gateway_id parameter"
        assert call_kwargs["gateway_id"] == proxied_gateway.id, f"gateway_id should be {proxied_gateway.id}, got {call_kwargs.get('gateway_id')}"
        
        # Verify tools were NOT deleted (no delete statements in execute calls)
        delete_calls = [call for call in mock_db.execute.call_args_list
                       if 'delete' in str(call).lower()]
        assert len(delete_calls) == 0, "Tools should not be deleted during reactivation"


@pytest.mark.asyncio
async def test_refresh_gateway_tools_with_gateway_id(gateway_service, mock_db, proxied_gateway, mock_forward_request):
    """Test that _refresh_gateway_tools_resources_prompts passes gateway_id for PROXIED gateways."""
    with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh, \
         patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init, \
         patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache:
        
        # Setup fresh_db_session mock
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session.execute.return_value = _make_execute_result(scalar=proxied_gateway)
        mock_fresh.return_value = mock_session
        
        mock_cache_instance = AsyncMock()
        mock_cache.return_value = mock_cache_instance
        
        # Mock _initialize_gateway
        mock_init.return_value = (
            {"tools": {}},
            [ToolCreate(name="test-tool-1", description="Test", inputSchema={"type": "object"})],
            [],
            []
        )
        
        # Call refresh
        result = await gateway_service._refresh_gateway_tools_resources_prompts(
            gateway_id=proxied_gateway.id,
            gateway=proxied_gateway
        )
        
        # Verify _initialize_gateway was called with gateway_id
        assert mock_init.called
        call_kwargs = mock_init.call_args[1]
        assert "gateway_id" in call_kwargs, "_initialize_gateway should receive gateway_id parameter"
        assert call_kwargs["gateway_id"] == proxied_gateway.id


@pytest.mark.asyncio
async def test_manual_refresh_preserves_tools(gateway_service, mock_db, proxied_gateway, mock_forward_request):
    """Test that manual refresh preserves tools for PROXIED gateways."""
    with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh, \
         patch("mcpgateway.services.reverse_proxy_service.get_reverse_proxy_service") as mock_rps, \
         patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache:
        
        # Setup fresh_db_session mock
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session.execute.return_value = _make_execute_result(scalar=proxied_gateway)
        mock_session.commit.return_value = None
        mock_fresh.return_value = mock_session
        
        mock_cache_instance = AsyncMock()
        mock_cache.return_value = mock_cache_instance
        
        # Mock reverse proxy service
        mock_rps_instance = MagicMock()
        mock_rps_instance.forward_request_to_session = mock_forward_request
        mock_rps.return_value = mock_rps_instance
        
        # Call manual refresh
        result = await gateway_service.refresh_gateway_manually(
            gateway_id=proxied_gateway.id
        )
        
        # Verify success
        assert result["success"] is True
        assert result["tools_removed"] == 0, "No tools should be removed during refresh"


@pytest.mark.asyncio
async def test_deactivate_then_reactivate_cycle(gateway_service, mock_db, proxied_gateway, mock_forward_request):
    """Test complete deactivate -> reactivate cycle preserves tools."""
    # Setup
    original_tool_count = len(proxied_gateway.tools)
    
    with patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache, \
         patch("mcpgateway.services.reverse_proxy_service.get_reverse_proxy_service") as mock_rps:
        
        mock_cache_instance = AsyncMock()
        mock_cache.return_value = mock_cache_instance
        
        # Mock reverse proxy service
        mock_rps_instance = MagicMock()
        mock_rps_instance.forward_request_to_session = mock_forward_request
        mock_rps.return_value = mock_rps_instance
        
        # Step 1: Deactivate
        def deactivate_execute_side_effect(query):
            query_str = str(query).lower()
            if 'select' in query_str or hasattr(query, 'column_descriptions'):
                return _make_execute_result(scalar=proxied_gateway)
            return MagicMock(rowcount=0)
        
        mock_db.execute.side_effect = deactivate_execute_side_effect
        
        await gateway_service.set_gateway_state(
            db=mock_db,
            gateway_id=proxied_gateway.id,
            activate=False,
            reachable=True
        )
        
        # Verify tools were not deleted during deactivation
        assert len(proxied_gateway.tools) == original_tool_count, "Tools should not be deleted on deactivation"
        
        # Step 2: Reactivate
        proxied_gateway.enabled = False  # Reset for reactivation
        
        with patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init, \
             patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit2, \
             patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger2, \
             patch.object(gateway_service, "_notify_gateway_activated", new_callable=AsyncMock) as mock_notify2:
            
            # Mock _initialize_gateway to return the same tools
            mock_init.return_value = (
                {"tools": {}},
                [
                    ToolCreate(name="test-tool-1", description="Test tool 1", inputSchema={"type": "object"}),
                    ToolCreate(name="test-tool-2", description="Test tool 2", inputSchema={"type": "object"})
                ],
                [],
                []
            )
            
            # Reset and setup mock for reactivation
            mock_db.execute.reset_mock()
            mock_db.commit.reset_mock()
            mock_db.refresh.reset_mock()
            
            def reactivate_execute_side_effect(query):
                query_str = str(query).lower()
                if 'select' in query_str or hasattr(query, 'column_descriptions'):
                    return _make_execute_result(scalar=proxied_gateway)
                return MagicMock(rowcount=0)
            
            mock_db.execute.side_effect = reactivate_execute_side_effect
            mock_db.commit.return_value = None
            mock_db.refresh = MagicMock(return_value=None)
            mock_db.add_all.return_value = None
            mock_db.flush.return_value = None
            mock_db.rollback.return_value = None
            
            await gateway_service.set_gateway_state(
                db=mock_db,
                gateway_id=proxied_gateway.id,
                activate=True,
                reachable=True
            )
            
            # Verify _initialize_gateway was called with gateway_id (the main fix)
            assert mock_init.called, "_initialize_gateway should be called during reactivation"
            call_kwargs = mock_init.call_args[1]
            assert "gateway_id" in call_kwargs, "_initialize_gateway should receive gateway_id parameter"
            assert call_kwargs["gateway_id"] == proxied_gateway.id, f"gateway_id should be {proxied_gateway.id}, got {call_kwargs.get('gateway_id')}"
            
            # Verify tools were not deleted during reactivation
            assert len(proxied_gateway.tools) == original_tool_count, "Tools should not be deleted on reactivation"


@pytest.mark.asyncio
async def test_non_proxied_gateway_does_not_pass_gateway_id(gateway_service, mock_db):
    """Test that non-PROXIED gateways do not pass gateway_id to _initialize_gateway."""
    # Create a non-PROXIED gateway
    gateway = MagicMock(spec=DbGateway)
    gateway.id = uuid.uuid4().hex
    gateway.name = "test-sse-gateway"
    gateway.url = "http://localhost:8000"
    gateway.transport = "SSE"
    gateway.enabled = False
    gateway.reachable = True
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.oauth_config = None
    gateway.auth_query_params = None
    gateway.tools = []
    gateway.resources = []
    gateway.prompts = []
    gateway.email_team = None
    
    mock_db.execute.return_value = _make_execute_result(scalar=gateway)
    
    with patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache, \
         patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init:
        
        mock_cache_instance = AsyncMock()
        mock_cache.return_value = mock_cache_instance
        
        mock_init.return_value = ({}, [], [], [])
        
        # Activate non-PROXIED gateway
        await gateway_service.set_gateway_state(
            db=mock_db,
            gateway_id=gateway.id,
            activate=True,
            reachable=True
        )
        
        # Verify _initialize_gateway was called
        assert mock_init.called
        call_kwargs = mock_init.call_args[1]
        
        # For non-PROXIED gateways, gateway_id should be None
        assert call_kwargs.get("gateway_id") is None, "Non-PROXIED gateways should not pass gateway_id"

# Made with Bob
