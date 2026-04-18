# -*- coding: utf-8 -*-
"""Unit tests for SIGHUP signal handler in mcpgateway.handlers.signal_handlers."""

# Standard
import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.handlers.signal_handlers import sighup_handler, sighup_reload


@pytest.mark.asyncio
async def test_sighup_reload_clears_ssl_cache_and_drains_upstream_registry_and_affinity():
    """sighup_reload() clears SSL cache + drains upstream registry + drains affinity mapping (#4205)."""
    mock_registry = MagicMock()
    mock_registry.close_all = AsyncMock()
    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache") as mock_clear,
        patch("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", return_value=mock_registry),
        patch("mcpgateway.services.session_affinity.drain_session_affinity", new_callable=AsyncMock) as mock_drain_affinity,
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    mock_clear.assert_called_once()
    mock_registry.close_all.assert_awaited_once()
    mock_drain_affinity.assert_awaited_once()
    info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
    assert any("SSL context cache cleared" in m for m in info_messages)
    assert any("upstream session registry drained" in m for m in info_messages)
    assert any("session-affinity mapping drained" in m for m in info_messages)


@pytest.mark.asyncio
async def test_sighup_reload_logs_error_on_ssl_cache_exception():
    """sighup_reload() catches and logs exceptions from clear_ssl_context_cache."""
    mock_registry = MagicMock()
    mock_registry.close_all = AsyncMock()
    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache", side_effect=RuntimeError("boom")),
        patch("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", return_value=mock_registry),
        patch("mcpgateway.services.session_affinity.drain_session_affinity", new_callable=AsyncMock),
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    mock_logger.error.assert_called_once()
    assert "boom" in mock_logger.error.call_args[0][0]


@pytest.mark.asyncio
async def test_sighup_reload_handles_affinity_drain_error():
    """sighup_reload() continues if the affinity drain fails."""
    mock_registry = MagicMock()
    mock_registry.close_all = AsyncMock()
    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache") as mock_clear,
        patch("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", return_value=mock_registry),
        patch(
            "mcpgateway.services.session_affinity.drain_session_affinity",
            new_callable=AsyncMock,
            side_effect=RuntimeError("affinity error"),
        ),
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    mock_clear.assert_called_once()
    mock_registry.close_all.assert_awaited_once()
    debug_messages = [call.args[0] for call in mock_logger.debug.call_args_list]
    assert any("affinity error" in m for m in debug_messages)


@pytest.mark.asyncio
async def test_sighup_reload_logs_warning_on_registry_drain_failure():
    """A generic exception from close_all() surfaces as WARNING so TLS rotation issues aren't silent."""
    mock_registry = MagicMock()
    mock_registry.close_all = AsyncMock(side_effect=RuntimeError("redis down during drain"))
    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache"),
        patch("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", return_value=mock_registry),
        patch("mcpgateway.services.session_affinity.drain_session_affinity", new_callable=AsyncMock),
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    mock_registry.close_all.assert_awaited_once()
    warning_messages = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("upstream session registry drain failed" in m and "redis down during drain" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_sighup_reload_handles_uninitialised_upstream_registry():
    """sighup_reload() logs at debug and keeps going when the upstream registry isn't initialised."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import RegistryNotInitializedError

    with (
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache") as mock_clear,
        patch(
            "mcpgateway.services.upstream_session_registry.get_upstream_session_registry",
            side_effect=RegistryNotInitializedError("not init"),
        ),
        patch("mcpgateway.services.session_affinity.drain_session_affinity", new_callable=AsyncMock),
        patch("mcpgateway.handlers.signal_handlers.logger") as mock_logger,
    ):
        await sighup_reload()
    mock_clear.assert_called_once()
    debug_messages = [call.args[0] for call in mock_logger.debug.call_args_list]
    assert any("upstream session registry not initialised" in m for m in debug_messages)


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

    mock_registry = MagicMock()
    mock_registry.close_all = AsyncMock()
    with (
        patch.object(loop, "create_task", side_effect=tracking_create_task),
        patch("mcpgateway.utils.ssl_context_cache.clear_ssl_context_cache"),
        patch("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", return_value=mock_registry),
        patch("mcpgateway.services.session_affinity.drain_session_affinity", new_callable=AsyncMock),
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


def test_install_sighup_handler_skips_outside_main_thread(monkeypatch):
    """main._install_sighup_handler() skips registration outside the main thread.

    Args:
        monkeypatch: Pytest fixture for runtime patching.
    """
    # First-Party
    import mcpgateway.main as main_mod

    mock_current = MagicMock()
    mock_current.name = "TestThread"
    mock_main = MagicMock()
    mock_main.name = "MainThread"
    monkeypatch.setattr(main_mod.threading, "current_thread", lambda: mock_current)
    monkeypatch.setattr(main_mod.threading, "main_thread", lambda: mock_main)
    mock_signal = MagicMock()
    monkeypatch.setattr(main_mod.signal, "signal", mock_signal)

    assert main_mod._install_sighup_handler() is False  # pylint: disable=protected-access
    mock_signal.assert_not_called()


def test_restore_default_sighup_handler_skips_outside_main_thread(monkeypatch):
    """main._restore_default_sighup_handler() skips reset outside the main thread.

    Args:
        monkeypatch: Pytest fixture for runtime patching.
    """
    # First-Party
    import mcpgateway.main as main_mod

    mock_current = MagicMock()
    mock_current.name = "TestThread"
    mock_main = MagicMock()
    mock_main.name = "MainThread"
    monkeypatch.setattr(main_mod.threading, "current_thread", lambda: mock_current)
    monkeypatch.setattr(main_mod.threading, "main_thread", lambda: mock_main)
    mock_signal = MagicMock()
    monkeypatch.setattr(main_mod.signal, "signal", mock_signal)

    main_mod._restore_default_sighup_handler()  # pylint: disable=protected-access
    mock_signal.assert_not_called()
