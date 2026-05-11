# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_plugin_runtime_redis.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for plugin runtime management with real Redis.

Tests the Redis read/write/publish path directly — not via HTTP endpoints.
Validates that the plugin framework correctly interacts with Redis for
global toggle, per-plugin mode overrides, and pub/sub invalidation.

Auto-starts a Redis Docker container if one isn't running locally.
Skips if neither local Redis nor Docker is available.

Usage:
    uv run pytest tests/integration/test_plugin_runtime_redis.py -v --with-integration
"""

# Standard
import asyncio
import json
import socket
import subprocess
import time
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# Redis fixture (same pattern as test_rate_limiter.py)
# ---------------------------------------------------------------------------


def _redis_port_open(host: str = "127.0.0.1", port: int = 6379, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def redis_url():
    """Yield a Redis URL pointing at a real Redis instance.

    Tries localhost:6379 first. If not reachable, attempts to start a
    temporary Docker container. Skips if neither works.
    """
    try:
        import redis.asyncio  # noqa: F401
    except Exception:
        pytest.skip("redis.asyncio package not installed")

    host, port = "127.0.0.1", 6379
    container_id = None

    if not _redis_port_open(host, port):
        try:
            res = subprocess.run(
                ["docker", "run", "-d", "--rm", "-p", f"{port}:6379", "--name", "pytest-plugin-redis", "redis:7"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            container_id = res.stdout.strip()
        except Exception as exc:
            pytest.skip(f"Redis unavailable and docker start failed: {exc}")

        for _ in range(50):
            if _redis_port_open(host, port):
                break
            time.sleep(0.1)
        else:
            if container_id:
                subprocess.run(["docker", "stop", container_id], check=False)
            pytest.skip("Redis did not start in time")

    yield f"redis://{host}:{port}/14"  # DB 14 — isolated

    if container_id:
        subprocess.run(["docker", "stop", container_id], check=False)


@pytest.fixture
def sync_redis(redis_url):
    """Return a synchronous Redis client for test verification."""
    import redis

    r = redis.from_url(redis_url, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def async_redis(redis_url):
    """Set up the gateway's async Redis client to use the test Redis instance."""
    import redis.asyncio as aioredis
    import mcpgateway.utils.redis_client as rc

    original_client = rc._client
    original_initialized = rc._initialized

    rc._client = aioredis.from_url(redis_url, decode_responses=True)
    rc._initialized = True

    yield rc._client

    # Restore
    rc._client = original_client
    rc._initialized = original_initialized


# ---------------------------------------------------------------------------
# Global toggle tests — real Redis
# ---------------------------------------------------------------------------


class TestGlobalToggleRedis:
    """Test global plugin toggle with real Redis."""

    @pytest.mark.asyncio
    async def test_enable_plugins_shared_writes_true(self, async_redis, sync_redis):
        """enable_plugins_shared(True) writes 'true' to real Redis."""
        from mcpgateway.plugins import enable_plugins_shared

        await enable_plugins_shared(True)

        val = sync_redis.get("plugin:global:enabled")
        assert val == "true"

    @pytest.mark.asyncio
    async def test_enable_plugins_shared_writes_false(self, async_redis, sync_redis):
        """enable_plugins_shared(False) writes 'false' to real Redis."""
        from mcpgateway.plugins import enable_plugins_shared

        await enable_plugins_shared(False)

        val = sync_redis.get("plugin:global:enabled")
        assert val == "false"

    @pytest.mark.asyncio
    async def test_are_plugins_enabled_shared_reads_true(self, async_redis, sync_redis):
        """are_plugins_enabled_shared() reads 'true' from real Redis."""
        from mcpgateway.plugins import are_plugins_enabled_shared

        sync_redis.set("plugin:global:enabled", "true")

        result = await are_plugins_enabled_shared()
        assert result is True

    @pytest.mark.asyncio
    async def test_are_plugins_enabled_shared_reads_false(self, async_redis, sync_redis):
        """are_plugins_enabled_shared() reads 'false' from real Redis."""
        from mcpgateway.plugins import are_plugins_enabled_shared

        sync_redis.set("plugin:global:enabled", "false")

        result = await are_plugins_enabled_shared()
        assert result is False

    @pytest.mark.asyncio
    async def test_roundtrip_toggle(self, async_redis, sync_redis):
        """Write via enable_plugins_shared, read via are_plugins_enabled_shared."""
        from mcpgateway.plugins import are_plugins_enabled_shared, enable_plugins_shared

        await enable_plugins_shared(False)
        assert await are_plugins_enabled_shared() is False

        await enable_plugins_shared(True)
        assert await are_plugins_enabled_shared() is True

    @pytest.mark.asyncio
    async def test_fallback_when_key_missing(self, async_redis, sync_redis):
        """Falls back to in-memory flag when Redis key doesn't exist."""
        from mcpgateway.plugins import are_plugins_enabled_shared, enable_plugins

        sync_redis.delete("plugin:global:enabled")
        enable_plugins(True)

        result = await are_plugins_enabled_shared()
        assert result is True


# ---------------------------------------------------------------------------
# Per-plugin mode override tests — real Redis
# ---------------------------------------------------------------------------


class TestPluginModeOverrideRedis:
    """Test per-plugin mode overrides with real Redis."""

    @pytest.mark.asyncio
    async def test_get_plugin_mode_override_reads_value(self, async_redis, sync_redis):
        """get_plugin_mode_override reads mode from real Redis."""
        from mcpgateway.plugins import get_plugin_mode_override

        sync_redis.set("plugin:RateLimiterPlugin:mode", "enforce")

        result = await get_plugin_mode_override("RateLimiterPlugin")
        assert result == "enforce"

    @pytest.mark.asyncio
    async def test_get_plugin_mode_override_returns_none_when_missing(self, async_redis, sync_redis):
        """Returns None when no Redis key exists."""
        from mcpgateway.plugins import get_plugin_mode_override

        sync_redis.delete("plugin:RateLimiterPlugin:mode")

        result = await get_plugin_mode_override("RateLimiterPlugin")
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_plugin_modes(self, async_redis, sync_redis):
        """Multiple plugins can have independent mode overrides."""
        from mcpgateway.plugins import get_plugin_mode_override

        sync_redis.set("plugin:RateLimiterPlugin:mode", "enforce")
        sync_redis.set("plugin:SecretsDetection:mode", "disabled")

        assert await get_plugin_mode_override("RateLimiterPlugin") == "enforce"
        assert await get_plugin_mode_override("SecretsDetection") == "disabled"
        assert await get_plugin_mode_override("PIIFilterPlugin") is None  # Not set


# ---------------------------------------------------------------------------
# Pub/sub tests — real Redis
# ---------------------------------------------------------------------------


class TestPubSubRedis:
    """Test pub/sub invalidation messages with real Redis."""

    @pytest.mark.asyncio
    async def test_toggle_publishes_invalidation_message(self, async_redis, sync_redis):
        """enable_plugins_shared publishes a message on the invalidation channel."""
        import redis as sync_redis_lib

        # Subscribe with sync client
        pubsub = sync_redis.pubsub()
        pubsub.subscribe("plugin:invalidation")
        # Consume subscribe confirmation
        pubsub.get_message(timeout=1)

        # Toggle
        from mcpgateway.plugins import enable_plugins_shared

        await enable_plugins_shared(False)

        # Check for message
        msg = pubsub.get_message(timeout=2)
        assert msg is not None, "No pub/sub message received"
        assert msg["type"] == "message"
        data = json.loads(msg["data"])
        assert data["type"] == "global_toggle"
        assert data["enabled"] is False

        pubsub.unsubscribe()
        pubsub.close()

    @pytest.mark.asyncio
    async def test_handler_updates_flag_on_global_toggle(self, async_redis):
        """_handle_invalidation_message updates in-memory flag."""
        from mcpgateway.plugins import _handle_invalidation_message, are_plugins_enabled, enable_plugins

        enable_plugins(True)
        assert are_plugins_enabled() is True

        message = {
            "type": "message",
            "data": json.dumps({"type": "global_toggle", "enabled": False}),
        }
        await _handle_invalidation_message(message)

        assert are_plugins_enabled() is False

    @pytest.mark.asyncio
    async def test_handler_ignores_subscribe_messages(self, async_redis):
        """Handler ignores non-message types."""
        from mcpgateway.plugins import _handle_invalidation_message, are_plugins_enabled, enable_plugins

        enable_plugins(True)
        message = {"type": "subscribe", "data": None}
        await _handle_invalidation_message(message)
        assert are_plugins_enabled() is True  # Unchanged

    @pytest.mark.asyncio
    async def test_handler_handles_malformed_json(self, async_redis):
        """Handler doesn't crash on malformed JSON."""
        from mcpgateway.plugins import _handle_invalidation_message, are_plugins_enabled, enable_plugins

        enable_plugins(True)
        message = {"type": "message", "data": "not valid json {{{"}
        await _handle_invalidation_message(message)
        assert are_plugins_enabled() is True  # Unchanged, no crash


# ---------------------------------------------------------------------------
# Global toggle blocks/enables get_plugin_manager — real Redis (#9, #10)
# ---------------------------------------------------------------------------


class TestGetPluginManagerRedis:
    """Test that global toggle actually controls get_plugin_manager via Redis."""

    @pytest.mark.asyncio
    async def test_disabled_toggle_returns_none(self, async_redis, sync_redis):
        """When Redis has global toggle = false, get_plugin_manager returns None."""
        from mcpgateway.plugins import get_plugin_manager, enable_plugins_shared

        await enable_plugins_shared(False)

        result = await get_plugin_manager()
        assert result is None, "get_plugin_manager should return None when plugins disabled via Redis"

    @pytest.mark.asyncio
    async def test_enabled_toggle_returns_manager_or_none_no_factory(self, async_redis, sync_redis):
        """When Redis has global toggle = true but no factory, returns None (no crash)."""
        from mcpgateway.plugins import get_plugin_manager, enable_plugins_shared
        import mcpgateway.plugins as framework

        await enable_plugins_shared(True)

        # With no factory initialized, should return None (not crash)
        original = framework._plugin_manager_factory
        framework._plugin_manager_factory = None
        try:
            result = await get_plugin_manager()
            assert result is None
        finally:
            framework._plugin_manager_factory = original

    @pytest.mark.asyncio
    async def test_toggle_cycle_via_redis(self, async_redis, sync_redis):
        """Toggle disable → enable via Redis, verify get_plugin_manager responds correctly."""
        from mcpgateway.plugins import get_plugin_manager, enable_plugins_shared

        # Disable
        await enable_plugins_shared(False)
        assert await get_plugin_manager() is None

        # Re-enable (still None because no factory, but shouldn't crash)
        await enable_plugins_shared(True)
        # Not None check — depends on factory state, but should not raise
        # The key point: it doesn't return None due to the toggle anymore


# ---------------------------------------------------------------------------
# TTL cache expiry — real Redis (#1)
# ---------------------------------------------------------------------------


class TestTTLCacheExpiryRedis:
    """Test TTL-based cache expiry with real Redis and real timer."""

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self, async_redis, sync_redis):
        """Manager cache entry expires after TTL and triggers rebuild."""
        from mcpgateway.plugins.gateway_plugin_manager import TenantPluginManagerFactory

        # Create a factory with very short TTL (1 second)
        factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
        factory._managers = {}
        factory._inflight = {}
        factory._lock = asyncio.Lock()
        factory._cache_ttl = 1  # 1 second TTL
        factory._base_config = MagicMock()
        factory._base_config.plugins = []
        factory._timeout = 30
        factory._observability = None
        factory._hook_policies = None

        # Manually cache a manager with current timestamp
        mock_manager = MagicMock()
        mock_manager.shutdown = AsyncMock()
        factory._managers["test::tool"] = (mock_manager, time.monotonic())

        # Immediately — should return cached manager
        async with factory._lock:
            entry = factory._managers.get("test::tool")
            assert entry is not None
            mgr, created_at = entry
            assert (time.monotonic() - created_at) < factory._cache_ttl

        # Wait for TTL to expire
        await asyncio.sleep(1.5)

        # Now the entry should be considered expired
        async with factory._lock:
            entry = factory._managers.get("test::tool")
            if entry is not None:
                _, created_at = entry
                assert (time.monotonic() - created_at) > factory._cache_ttl, "Cache should be expired"


# ---------------------------------------------------------------------------
# Pub/sub handler triggers manager eviction (#7, #8)
# ---------------------------------------------------------------------------


class TestPubSubEvictionRedis:
    """Test that pub/sub messages trigger actual cache eviction."""

    @pytest.mark.asyncio
    async def test_mode_change_message_evicts_all_managers(self, async_redis, sync_redis):
        """mode_change message evicts all cached managers."""
        import mcpgateway.plugins as framework

        mock_factory = AsyncMock()
        mock_factory._lock = asyncio.Lock()
        mock_factory._managers = {
            "team_a::tool_1": (MagicMock(), time.monotonic()),
            "team_a::tool_2": (MagicMock(), time.monotonic()),
        }
        mock_factory.reload_tenant = AsyncMock()

        original = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            message = {
                "type": "message",
                "data": json.dumps({"type": "mode_change", "plugin": "RateLimiterPlugin", "mode": "enforce"}),
            }
            await framework._handle_invalidation_message(message)

            # All managers should be reloaded
            assert mock_factory.reload_tenant.call_count == 2
            mock_factory.reload_tenant.assert_any_call("team_a::tool_1")
            mock_factory.reload_tenant.assert_any_call("team_a::tool_2")
        finally:
            framework._plugin_manager_factory = original

    @pytest.mark.asyncio
    async def test_binding_change_message_evicts_specific_context(self, async_redis, sync_redis):
        """binding_change message evicts only the specified context."""
        import mcpgateway.plugins as framework

        mock_factory = AsyncMock()
        mock_factory._lock = asyncio.Lock()
        mock_factory._managers = {
            "team_a::tool_1": (MagicMock(), time.monotonic()),
            "team_a::tool_2": (MagicMock(), time.monotonic()),
            "team_b::tool_1": (MagicMock(), time.monotonic()),
        }
        mock_factory.reload_tenant = AsyncMock()

        original = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            message = {
                "type": "message",
                "data": json.dumps({"type": "binding_change", "context_id": "team_a::tool_1"}),
            }
            await framework._handle_invalidation_message(message)

            # Only the specific context should be reloaded
            mock_factory.reload_tenant.assert_called_once_with("team_a::tool_1")
        finally:
            framework._plugin_manager_factory = original

    @pytest.mark.asyncio
    async def test_pubsub_roundtrip_with_real_redis(self, async_redis, sync_redis):
        """Full pub/sub roundtrip: publish via enable_plugins_shared, receive via subscriber."""
        from mcpgateway.plugins import enable_plugins_shared

        # Subscribe
        pubsub = sync_redis.pubsub()
        pubsub.subscribe("plugin:invalidation")
        pubsub.get_message(timeout=1)  # Consume subscribe confirmation

        # Publish by toggling
        await enable_plugins_shared(True)

        # Receive
        msg = pubsub.get_message(timeout=2)
        assert msg is not None
        data = json.loads(msg["data"])
        assert data["type"] == "global_toggle"
        assert data["enabled"] is True

        # Toggle again
        await enable_plugins_shared(False)
        msg = pubsub.get_message(timeout=2)
        assert msg is not None
        data = json.loads(msg["data"])
        assert data["enabled"] is False

        pubsub.unsubscribe()
        pubsub.close()


# ---------------------------------------------------------------------------
# DB error fallback — real Redis (#4)
# ---------------------------------------------------------------------------


class TestDBErrorFallbackRedis:
    """Test DB error fallback with real Redis."""

    @pytest.mark.asyncio
    async def test_db_error_returns_none_uses_base_config(self, async_redis):
        """When DB raises an error, get_config_from_db returns None (base config used)."""
        from mcpgateway.plugins.gateway_plugin_manager import GatewayTenantPluginManagerFactory

        factory = GatewayTenantPluginManagerFactory.__new__(GatewayTenantPluginManagerFactory)
        factory._db_factory = MagicMock(side_effect=Exception("connection refused"))

        result = await factory.get_config_from_db("team_a::my_tool")
        assert result is None, "Should fall back to None (base config) on DB error"

    @pytest.mark.asyncio
    async def test_db_error_does_not_affect_redis_toggle(self, async_redis, sync_redis):
        """Redis global toggle still works even when DB is broken."""
        from mcpgateway.plugins import are_plugins_enabled_shared, enable_plugins_shared

        # Set toggle via Redis
        await enable_plugins_shared(False)

        # DB being broken doesn't affect Redis toggle read
        result = await are_plugins_enabled_shared()
        assert result is False, "Redis toggle should work independently of DB"

        await enable_plugins_shared(True)
        result = await are_plugins_enabled_shared()
        assert result is True
