# -*- coding: utf-8 -*-
"""Unit tests for SIGHUP signal handler in mcpgateway.handlers.signal_handlers."""

# Standard
import asyncio
import signal
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.handlers.signal_handlers import sighup_handler, sighup_reload


@pytest.mark.asyncio
async def test_sighup_reload_clears_ssl_cache_and_session_pool():
    """sighup_reload() clears SSL context cache and closes MCP session pool."""
    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache") as mock_clear,
        patch("mcpgateway.services.mcp_session_pool.drain_mcp_session_pool", new_callable=AsyncMock) as mock_pool_close,
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    mock_clear.assert_called_once()
    mock_pool_close.assert_awaited_once()
    info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
    assert any("SSL context cache cleared" in m for m in info_messages)
    assert any("session pool drained" in m for m in info_messages)


@pytest.mark.asyncio
async def test_sighup_reload_logs_error_on_ssl_cache_exception():
    """sighup_reload() catches and logs exceptions from clear_ssl_context_cache."""
    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache", side_effect=RuntimeError("boom")),
        patch("mcpgateway.services.mcp_session_pool.drain_mcp_session_pool", new_callable=AsyncMock),
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    mock_logger.error.assert_called_once()
    assert "boom" in mock_logger.error.call_args[0][0]


@pytest.mark.asyncio
async def test_sighup_reload_handles_session_pool_error():
    """sighup_reload() continues if session pool close fails."""
    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache") as mock_clear,
        patch("mcpgateway.services.mcp_session_pool.drain_mcp_session_pool", new_callable=AsyncMock, side_effect=RuntimeError("pool error")),
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    # SSL cache should still be cleared
    mock_clear.assert_called_once()
    # Pool error should be logged at debug level
    debug_messages = [call.args[0] for call in mock_logger.debug.call_args_list]
    assert any("pool error" in m for m in debug_messages)


@pytest.mark.asyncio
async def test_sighup_handler_schedules_task():
    """sighup_handler() schedules sighup_reload on the running event loop."""
    loop = asyncio.get_running_loop()
    task_created = False
    original_create_task = loop.create_task

    def tracking_create_task(coro, **kwargs):
        nonlocal task_created
        task_created = True
        return original_create_task(coro, **kwargs)

    with (
        patch.object(loop, "create_task", side_effect=tracking_create_task),
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache"),
        patch("mcpgateway.services.mcp_session_pool.drain_mcp_session_pool", new_callable=AsyncMock),
    ):
        sighup_handler(signal.SIGHUP, None)
        await asyncio.sleep(0.05)

    assert task_created


def test_sighup_handler_logs_warning_when_no_event_loop():
    """sighup_handler() logs warning when no event loop is running."""
    with (
        patch("mcpgateway.handlers.signal_handlers.asyncio.get_running_loop", side_effect=RuntimeError("No loop")),
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        sighup_handler(signal.SIGHUP, None)
    mock_logger.warning.assert_called_once()
    assert "not running" in mock_logger.warning.call_args[0][0]
