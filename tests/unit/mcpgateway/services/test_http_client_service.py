# -*- coding: utf-8 -*-
"""Tests for mcpgateway.services.http_client_service."""

from __future__ import annotations

import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcpgateway.services.http_client_service import (
    SharedHttpClient,
    get_admin_timeout,
    get_default_verify,
    get_http_client,
    get_http_limits,
    get_http_timeout,
    get_isolated_http_client,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset SharedHttpClient singleton between tests."""
    SharedHttpClient._instance = None
    SharedHttpClient._lock = __import__("asyncio").Lock()
    yield
    SharedHttpClient._instance = None


# --- SharedHttpClient ---


def test_constructor():
    """SharedHttpClient.__init__ sets defaults."""
    c = SharedHttpClient()
    assert c._client is None
    assert c._initialized is False
    assert c._limits is None


@pytest.mark.asyncio
async def test_get_instance_creates_singleton():
    """get_instance returns same initialized instance."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 10
        mock_settings.httpx_max_keepalive_connections = 5
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        instance = await SharedHttpClient.get_instance()
        assert instance._initialized is True
        assert instance._client is not None

        # Same instance on second call
        instance2 = await SharedHttpClient.get_instance()
        assert instance is instance2

        await instance.close()


@pytest.mark.asyncio
async def test_get_instance_concurrent_second_check_skips_reinitialize(monkeypatch):
    """Cover concurrent path where second caller sees already initialized instance inside lock."""
    started = asyncio.Event()
    allow_finish = asyncio.Event()
    init_calls = 0

    async def _fake_initialize(self):
        nonlocal init_calls
        init_calls += 1
        started.set()
        await allow_finish.wait()
        self._client = MagicMock()
        self._initialized = True

    monkeypatch.setattr(SharedHttpClient, "_initialize", _fake_initialize)

    task1 = asyncio.create_task(SharedHttpClient.get_instance())
    await started.wait()
    task2 = asyncio.create_task(SharedHttpClient.get_instance())
    allow_finish.set()

    inst1, inst2 = await asyncio.gather(task1, task2)
    assert inst1 is inst2
    assert init_calls == 1


@pytest.mark.asyncio
async def test_client_property_raises_when_not_initialized():
    """client property raises RuntimeError before initialization."""
    c = SharedHttpClient()
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = c.client


@pytest.mark.asyncio
async def test_client_property_returns_client():
    """client property returns the httpx client after initialization."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 10
        mock_settings.httpx_max_keepalive_connections = 5
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        instance = await SharedHttpClient.get_instance()
        client = instance.client
        assert isinstance(client, httpx.AsyncClient)
        await instance.close()


def test_get_pool_stats_not_initialized():
    """get_pool_stats returns empty dict when client is None."""
    c = SharedHttpClient()
    assert c.get_pool_stats() == {}


@pytest.mark.asyncio
async def test_get_pool_stats_with_limits():
    """get_pool_stats returns limits when initialized."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 200
        mock_settings.httpx_max_keepalive_connections = 100
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        instance = await SharedHttpClient.get_instance()
        stats = instance.get_pool_stats()
        assert stats["max_connections"] == 200
        assert stats["max_keepalive"] == 100
        await instance.close()


def test_get_pool_stats_no_limits():
    """get_pool_stats returns empty dict when _limits is None but client exists."""
    c = SharedHttpClient()
    c._client = MagicMock()  # client set but no limits
    c._limits = None
    assert c.get_pool_stats() == {}


@pytest.mark.asyncio
async def test_close():
    """close() shuts down client and resets state."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 10
        mock_settings.httpx_max_keepalive_connections = 5
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        instance = await SharedHttpClient.get_instance()
        assert instance._initialized is True
        await instance.close()
        assert instance._client is None
        assert instance._initialized is False
        assert instance._limits is None


@pytest.mark.asyncio
async def test_close_noop_when_no_client():
    """close() is a no-op when client is None."""
    c = SharedHttpClient()
    await c.close()  # Should not raise


@pytest.mark.asyncio
async def test_shutdown():
    """shutdown() closes the singleton and clears instance."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 10
        mock_settings.httpx_max_keepalive_connections = 5
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        await SharedHttpClient.get_instance()
        assert SharedHttpClient._instance is not None
        await SharedHttpClient.shutdown()
        assert SharedHttpClient._instance is None


@pytest.mark.asyncio
async def test_shutdown_noop_when_no_instance():
    """shutdown() is a no-op when no instance exists."""
    await SharedHttpClient.shutdown()  # Should not raise


# --- Module-level convenience functions ---


@pytest.mark.asyncio
async def test_get_http_client():
    """get_http_client() returns the shared client."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 10
        mock_settings.httpx_max_keepalive_connections = 5
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        client = await get_http_client()
        assert isinstance(client, httpx.AsyncClient)
        await SharedHttpClient.shutdown()


def test_get_http_limits():
    """get_http_limits() returns configured Limits."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 50
        mock_settings.httpx_max_keepalive_connections = 25
        mock_settings.httpx_keepalive_expiry = 60

        limits = get_http_limits()
        assert isinstance(limits, httpx.Limits)
        assert limits.max_connections == 50
        assert limits.max_keepalive_connections == 25


def test_get_http_timeout_defaults():
    """get_http_timeout() uses settings defaults."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10

        timeout = get_http_timeout()
        assert timeout.connect == 5
        assert timeout.read == 120
        assert timeout.write == 30
        assert timeout.pool == 10


def test_get_http_timeout_overrides():
    """get_http_timeout() allows overriding individual values."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10

        timeout = get_http_timeout(read_timeout=60, connect_timeout=3)
        assert timeout.read == 60
        assert timeout.connect == 3
        assert timeout.write == 30
        assert timeout.pool == 10


def test_get_admin_timeout():
    """get_admin_timeout() returns shorter admin timeout."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_admin_read_timeout = 30
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10

        timeout = get_admin_timeout()
        assert timeout.read == 30
        assert timeout.connect == 5


def test_get_default_verify_true():
    """get_default_verify() returns True when skip_ssl_verify is False."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.skip_ssl_verify = False
        assert get_default_verify() is True


def test_get_default_verify_false():
    """get_default_verify() returns False when skip_ssl_verify is True."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.skip_ssl_verify = True
        assert get_default_verify() is False


@pytest.mark.asyncio
async def test_get_isolated_http_client():
    """get_isolated_http_client() yields a working client."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 10
        mock_settings.httpx_max_keepalive_connections = 5
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        async with get_isolated_http_client(timeout=60) as client:
            assert isinstance(client, httpx.AsyncClient)


@pytest.mark.asyncio
async def test_get_isolated_http_client_with_explicit_verify():
    """get_isolated_http_client() respects explicit verify parameter."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.httpx_max_connections = 10
        mock_settings.httpx_max_keepalive_connections = 5
        mock_settings.httpx_keepalive_expiry = 30
        mock_settings.httpx_connect_timeout = 5
        mock_settings.httpx_read_timeout = 120
        mock_settings.httpx_write_timeout = 30
        mock_settings.httpx_pool_timeout = 10
        mock_settings.httpx_http2_enabled = False
        mock_settings.skip_ssl_verify = False

        async with get_isolated_http_client(verify=False, http2=True) as client:
            assert isinstance(client, httpx.AsyncClient)
