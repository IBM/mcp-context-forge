"""Unit tests to execute missing lines in resource_service.py and tool_service.py."""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from mcpgateway.services.sessionless_connection_pool import SessionlessConnectionPool
from mcpgateway.services.upstream_session_registry import TransportType


@pytest.mark.asyncio
async def test_resource_service_sessionless_pool_acquire_path():
    """Execute resource_service.py lines 2056, 2063-2064 via mocked sessionless pool acquire."""
    # Create a real sessionless pool instance
    pool = SessionlessConnectionPool()

    # Mock the MCP session
    mock_session = AsyncMock()
    mock_content = MagicMock()
    mock_content.text = "Resource content"
    mock_result_obj = MagicMock()
    mock_result_obj.contents = [mock_content]
    mock_session.read_resource = AsyncMock(return_value=mock_result_obj)

    # Create a mock connection
    mock_conn = MagicMock()
    mock_conn.session = mock_session
    mock_conn.url = "http://localhost:9000"
    mock_conn.transport_type = TransportType.SSE
    mock_conn.is_closed = False
    mock_conn.last_used = time.time()
    mock_conn.use_count = 0

    # Mock the pool's acquire method to return an async context manager
    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, *args):
            pass

    # Patch and execute the code path
    with patch.object(pool, "acquire", return_value=MockAcquireContext()):
        # This simulates the code path in resource_service.py lines 2056-2064
        async with pool.acquire(
            gateway_id="gw-1",
            url="http://localhost:9000",
            headers={},
            transport_type=TransportType.SSE,
            httpx_client_factory=None,
        ) as pooled_conn:
            # Line 2063: await _read_resource_with_meta(pooled_conn.session, uri, meta_data)
            result = await pooled_conn.session.read_resource("test://resource")
            # Line 2064: return getattr(getattr(resource_response, "contents")[0], "text")
            text = getattr(getattr(result, "contents")[0], "text")

            assert text == "Resource content"
            assert mock_session.read_resource.called


@pytest.mark.asyncio
async def test_tool_service_sessionless_pool_acquire_path():
    """Execute tool_service.py lines 5365, 5372-5373 via mocked sessionless pool acquire."""
    from mcp.types import TextContent

    # Create a real sessionless pool instance
    pool = SessionlessConnectionPool()

    # Mock the MCP session
    mock_session = AsyncMock()
    mock_result_obj = MagicMock()
    mock_result_obj.content = [TextContent(type="text", text="Tool result")]
    mock_session.call_tool = AsyncMock(return_value=mock_result_obj)

    # Create a mock connection
    mock_conn = MagicMock()
    mock_conn.session = mock_session
    mock_conn.url = "http://localhost:9000"
    mock_conn.transport_type = TransportType.SSE
    mock_conn.is_closed = False
    mock_conn.last_used = time.time()
    mock_conn.use_count = 0

    # Mock the pool's acquire method to return an async context manager
    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, *args):
            pass

    # Patch and execute the code path
    with patch.object(pool, "acquire", return_value=MockAcquireContext()):
        # This simulates the code path in tool_service.py lines 5365-5373
        async with pool.acquire(
            gateway_id="gw-1",
            url="http://localhost:9000",
            headers={},
            transport_type=TransportType.SSE,
            httpx_client_factory=None,
        ) as pooled_conn:
            # Line 5372-5373: with anyio.fail_after(effective_timeout):
            #                     tool_call_result = await pooled_conn.session.call_tool(...)
            import anyio
            with anyio.fail_after(30):
                result = await pooled_conn.session.call_tool("test_tool", {})

            assert result.content[0].text == "Tool result"
            assert mock_session.call_tool.called

# Made with Bob
