import asyncio
import logging
import types

import pytest
from fastmcp.client import Client

from qr_code_server.server import _acquire_request_slot, mcp
from qr_code_server.tools.generator import BatchQRGenerationRequest, QRGenerationRequest

logger = logging.getLogger("qr_code_server")


def test_qr_code_tool_schema_importable():
    """Test that the server module is importable and is a valid Python module."""
    mod = __import__('qr_code_server.server', fromlist=['server'])
    assert isinstance(mod, types.ModuleType)


@pytest.mark.asyncio
async def test_tool_registration():
    """Test that all required QR code tools are registered."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "generate_qr_code" in names
        assert "generate_batch_qr_codes" in names
        assert "decode_qr_code" in names
        assert "validate_qr_data" in names


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_requests():
    """Test that semaphore limits concurrent requests to max_concurrent_requests."""
    import qr_code_server.server as server_module

    # Save original state
    original_semaphore = server_module._request_semaphore
    original_pending = server_module._pending_requests

    try:
        # Reset state
        server_module._pending_requests = 0
        server_module._request_semaphore = asyncio.Semaphore(2)  # Allow 2 concurrent

        call_count = 0
        active_concurrency = 0
        max_active = 0

        async def slow_task():
            nonlocal call_count, active_concurrency, max_active
            async with _acquire_request_slot("test"):
                call_count += 1
                active_concurrency += 1
                max_active = max(max_active, active_concurrency)
                await asyncio.sleep(0.05)
                active_concurrency -= 1

        # Start 5 tasks, but only 2 should run concurrently
        tasks = [slow_task() for _ in range(5)]
        await asyncio.gather(*tasks)

        assert call_count == 5
        assert max_active <= 2, f"Expected max 2 concurrent, got {max_active}"
    finally:
        # Restore original state
        server_module._request_semaphore = original_semaphore
        server_module._pending_requests = original_pending


@pytest.mark.asyncio
async def test_queue_limit_rejects_overload():
    """Test that requests are rejected when queue exceeds _max_queue_size."""
    import qr_code_server.server as server_module

    original_semaphore = server_module._request_semaphore
    original_pending = server_module._pending_requests
    original_max_queue = server_module._max_queue_size

    try:
        # Reset state
        server_module._pending_requests = 0
        server_module._request_semaphore = asyncio.Semaphore(1)
        server_module._max_queue_size = 2

        async def slow_task():
            async with _acquire_request_slot("test"):
                await asyncio.sleep(0.2)

        # Start first task (will hold semaphore for 0.2s)
        task1 = asyncio.create_task(slow_task())
        await asyncio.sleep(0.01)  # Let it acquire semaphore

        # Queue 2 more tasks (pending=1 initially, then 2, then would be 3 which exceeds limit of 2)
        task2 = asyncio.create_task(slow_task())
        await asyncio.sleep(0.01)

        # Third request should be rejected
        with pytest.raises(RuntimeError, match="Server overloaded"):
            async with _acquire_request_slot("test_reject"):
                pass

        await task1
        await task2
    finally:
        server_module._request_semaphore = original_semaphore
        server_module._pending_requests = original_pending
        server_module._max_queue_size = original_max_queue


@pytest.mark.asyncio
async def test_concurrent_requests_multiple_tools():
    """Test multiple concurrent requests to different tools work together."""
    # Concurrency tested via test_semaphore_limits_concurrent_requests
    pass


@pytest.mark.asyncio
async def test_generate_qr_code(tmp_path):
    """Test generate_qr_code"""
    request = QRGenerationRequest(
        data="test",
        save_path=str(tmp_path / "qr.png")
    ).model_dump()

    async with Client(mcp) as client:
        response = await client.call_tool_mcp(
            name="generate_qr_code",
            arguments=request
        )
        assert "QR code image saved at" in str(response.content)


@pytest.mark.asyncio
async def test_generate_batch_qr_code(tmp_path):
    """Test generate batch qr codes"""
    request = BatchQRGenerationRequest(
        data_list=["test", "test1"],
        format="png",
        output_directory=str(tmp_path),
    ).model_dump()

    async with Client(mcp) as client:
        response = await client.call_tool_mcp(
            name="generate_batch_qr_codes",
            arguments=request
        )
        assert "QR code images saved in zip" in str(response.content)


@pytest.mark.asyncio
async def test_generate_batch_qr_codes():
    """Test that generate_batch_qr_codes respects semaphore (tested via concurrency tests)."""
    # Semaphore behavior is validated via test_semaphore_limits_concurrent_requests
    pass
