# -*- coding: utf-8 -*-
import asyncio
import logging
import stat
import types
from unittest.mock import MagicMock, patch

import pytest
from fastmcp.client import Client

from qr_code_server.server import _acquire_request_slot, main, mcp
from qr_code_server.tools.decoder import QRDecodingRequest
from qr_code_server.tools.generator import BatchQRGenerationRequest, QRGenerationRequest
from qr_code_server.tools.validator import QRValidationRequest

logger = logging.getLogger("qr_code_server")


def test_qr_code_tool_schema_importable():
    """Test that the server module is importable and is a valid Python module."""
    mod = __import__("qr_code_server.server", fromlist=["server"])
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
async def test_generate_qr_code(tmp_path):
    """Test generate_qr_code"""
    request = QRGenerationRequest(data="test", save_path=str(tmp_path / "qr.png")).model_dump()

    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="generate_qr_code", arguments=request)
        assert "QR code image saved at" in str(response.content)


@pytest.mark.asyncio
async def test_generate_qr_code_fails(tmp_path):
    """Test generate_qr_code fails"""
    tmp_path.chmod(stat.S_IRUSR)
    request = QRGenerationRequest(data="test", save_path=str(tmp_path)).model_dump()

    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="generate_qr_code", arguments=request)
        assert "[Errno 13]" in str(response.content)


@pytest.mark.asyncio
async def test_generate_batch_qr_code(tmp_path):
    """Test generate batch qr codes"""
    request = BatchQRGenerationRequest(
        data_list=["test", "test1"],
        format="png",
        output_directory=str(tmp_path),
    ).model_dump()
    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="generate_batch_qr_codes", arguments=request)
        assert "QR code images saved in zip" in str(response.content)


@pytest.mark.asyncio
async def test_generate_batch_qr_code_fails(tmp_path):
    """Test generate batch qr codes fails"""
    tmp_path.chmod(stat.S_IRUSR)
    request = BatchQRGenerationRequest(
        data_list=["test", "test1"],
        format="png",
        output_directory=str(tmp_path),
    ).model_dump()
    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="generate_batch_qr_codes", arguments=request)
        # OS Permission Error
        assert "[Errno 13]" in str(response.content)


@pytest.mark.asyncio
async def test_decode_qr_code():
    """Test generate decode qr codes image base64"""
    image = (
        "iVBORw0KGgoAAAANSUhEUgAAASIAAAEiAQAAAAB1xeIbAAABm0lEQVR4nO2ZwW2lQBBEX++M5CMjOQCHAhk41s2ACWU"
        "DsMQcLYFqDwOs/7es9YUPhubAofUkSqim6S5M/P/Kv74BgVNOOeWUU0enbL4iUCJQlkq3q65LUK0kaQDyy7tZR5Ak6Z"
        "Z6vK5LUGX1eHmqb3w+BjvrOjMV7wutQJTtnujUl1S2iHWPfOJlqcX3jYACBrPvPy5dR1V/CiqbmVkC2gGsY6pjzt66Tk"
        "1V3//z+GL526jhqOrPQFnHZLXVW5qMnCb7TD1e1xUo9SUCzViL1hFkHZPvVltS1BWqHcLNTSPqCapLV39U9T+bmuecnAL"
        "KL+9GTgEoz4Lmzb+1W1KL7zUiDSANQeobqbYg9/121DrnBEEjDALWDlNUft1R1xUoPkZmhDlQA5jPgvt+M2rtOZI0BC21"
        "sd685zyAWnJM9Y1kloLIKUj9zrrOTN3nmAZxpP0dR6OZIm2/j64rUrXT5DQZ7Z8n/3eyJXWfY0JJKL8OAOMS6xxV/c+m7"
        "ucc2rrmsoz7/q3djPqcY7LmmM1aPqp6p5xyyimnvkv9BVqy01GUeGtxAAAAAElFTkSuQmCC"
    )
    encoded_string = "test_passed :)"
    request = QRDecodingRequest(
        image_data=image,
    ).model_dump()
    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="decode_qr_code", arguments=request)
        assert encoded_string in str(response.content)


@pytest.mark.asyncio
async def test_decode_qr_code_fails():
    """Test generate decode qr codes image base64 fail"""
    image = "No image here"
    request = QRDecodingRequest(
        image_data=image,
    ).model_dump()
    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="decode_qr_code", arguments=request)
        assert "could not load image from file or as base64" in str(response.content).lower()


@pytest.mark.asyncio
async def test_decode_qr_code_generic_exception():
    with patch(
        "qr_code_server.server.qr_decode",
        side_effect=Exception("Not working"),
    ):
        request = QRDecodingRequest(
            image_data="image",
        ).model_dump()

        async with Client(mcp) as client:
            response = await client.call_tool_mcp(
                name="decode_qr_code",
                arguments=request,
            )
        assert "Not working" in str(response.content)


@pytest.mark.asyncio
async def test_validate_qr_data():
    """Test validate qr data"""
    request = QRValidationRequest(
        data="small test data",
        target_version=10,
    ).model_dump()
    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="validate_qr_data", arguments=request)
        assert "suggested_version" in str(response.content)


@pytest.mark.asyncio
async def test_validate_qr_data_fails():
    """Test validate qr data fails"""
    request = QRValidationRequest(
        data="test" * 100,
        target_version=1,
        error_correction="H",
        check_capacity=True,
        suggest_optimization=False,
    ).model_dump()
    async with Client(mcp) as client:
        response = await client.call_tool_mcp(name="validate_qr_data", arguments=request)
        assert "Data does not fit" in str(response.content)


@pytest.mark.asyncio
async def test_generate_qr_code_runtime_error(tmp_path):
    """Test that RuntimeError from request slot acquisition is handled"""
    with patch("qr_code_server.server._acquire_request_slot") as mock_acquire:
        mock_acquire.return_value.__aenter__.side_effect = RuntimeError(
            "Server overloaded. Max queue size (30) exceeded."
        )
        request = QRGenerationRequest(data="test", save_path=str(tmp_path)).model_dump()

        async with Client(mcp) as client:
            response = await client.call_tool(name="generate_qr_code", arguments=request)
        assert "Server overload" in str(response.content)


@pytest.mark.asyncio
async def test_generate_batch_qr_codes_runtime_error(tmp_path):
    """Test that RuntimeError from request slot acquisition is handled"""
    with patch("qr_code_server.server._acquire_request_slot") as mock_acquire:
        mock_acquire.return_value.__aenter__.side_effect = RuntimeError(
            "Server overloaded. Max queue size (30) exceeded."
        )
        request = BatchQRGenerationRequest(
            data_list=["test1", "test2"], output_directory=str(tmp_path)
        ).model_dump()

        async with Client(mcp) as client:
            response = await client.call_tool(name="generate_batch_qr_codes", arguments=request)

        assert "Server overload" in str(response.content)


@pytest.mark.asyncio
async def test_decode_qr_code_runtime_error():
    """Test that RuntimeError from request slot acquisition is handled"""
    with patch("qr_code_server.server._acquire_request_slot") as mock_acquire:
        mock_acquire.return_value.__aenter__.side_effect = RuntimeError(
            "Server overloaded. Max queue size (30) exceeded."
        )
        request = QRDecodingRequest(
            image_data="base64_encoded_data", image_format="png"
        ).model_dump()

        async with Client(mcp) as client:
            response = await client.call_tool(name="decode_qr_code", arguments=request)

        assert "Server overload" in str(response.content)


@pytest.mark.asyncio
async def test_validate_qr_data_runtime_error():
    """Test that RuntimeError from request slot acquisition is handled"""
    with patch("qr_code_server.server._acquire_request_slot") as mock_acquire:
        mock_acquire.return_value.__aenter__.side_effect = RuntimeError(
            "Server overloaded. Max queue size (30) exceeded."
        )
        request = QRValidationRequest(data="test data", error_correction="M").model_dump()

        async with Client(mcp) as client:
            response = await client.call_tool(name="validate_qr_data", arguments=request)

        assert "Server overload" in str(response.content)


@pytest.mark.parametrize(
    "transport,expected_call_args",
    [("stdio", ()), ("http", {"transport": "http", "host": "127.0.0.1", "port": 8080})],
)
def test_main_transport(monkeypatch, transport, expected_call_args):
    """Test main() with different transport modes without actually starting server."""

    class Args:
        def __init__(self, transport, host="127.0.0.1", port=8080):
            self.transport = transport
            self.host = host
            self.port = port

    monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda self: Args(transport))

    # Mock mcp.run so server never actually starts
    mock_run = MagicMock()
    monkeypatch.setattr(mcp, "run", mock_run)

    main()

    if transport == "stdio":
        mock_run.assert_called_once_with()
    else:
        mock_run.assert_called_once_with(**expected_call_args)


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
