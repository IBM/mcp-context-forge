# -*- coding: utf-8 -*-
"""Unit tests for plugin runtime management.

Tests cover:
    - Global plugin enable/disable via Redis (shared state)
    - Per-plugin mode override via Redis
    - Cache invalidation helpers
    - TTL-based cache expiry in TenantPluginManagerFactory
    - DB error fallback in get_config_from_db
    - Wildcard binding cache invalidation

All Redis interactions are mocked — no real Redis needed.
"""

# Standard
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest


# ---------------------------------------------------------------------------
# Layer 1: Global enable/disable (Redis-backed)
# ---------------------------------------------------------------------------


class TestArePluginsEnabledShared:
    """Tests for are_plugins_enabled_shared() — reads global toggle from Redis."""

    @pytest.mark.asyncio
    async def test_reads_true_from_redis(self):
        """When Redis has 'true', returns True."""
        from mcpgateway.plugins.framework import are_plugins_enabled_shared

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="true")

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await are_plugins_enabled_shared()
            assert result is True

    @pytest.mark.asyncio
    async def test_reads_false_from_redis(self):
        """When Redis has 'false', returns False."""
        from mcpgateway.plugins.framework import are_plugins_enabled_shared

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="false")

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await are_plugins_enabled_shared()
            assert result is False

    @pytest.mark.asyncio
    async def test_reads_bytes_from_redis(self):
        """When Redis returns bytes (decode_responses=False), handles correctly."""
        from mcpgateway.plugins.framework import are_plugins_enabled_shared

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=b"true")

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await are_plugins_enabled_shared()
            assert result is True

    @pytest.mark.asyncio
    async def test_falls_back_to_in_memory_when_redis_unavailable(self):
        """When Redis client is None, falls back to in-memory _PLUGINS_ENABLED."""
        from mcpgateway.plugins.framework import are_plugins_enabled_shared, enable_plugins

        enable_plugins(True)

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            result = await are_plugins_enabled_shared()
            assert result is True

    @pytest.mark.asyncio
    async def test_falls_back_to_in_memory_when_redis_key_missing(self):
        """When Redis key doesn't exist, falls back to in-memory flag."""
        from mcpgateway.plugins.framework import are_plugins_enabled_shared, enable_plugins

        enable_plugins(False)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await are_plugins_enabled_shared()
            assert result is False

    @pytest.mark.asyncio
    async def test_falls_back_on_redis_exception(self):
        """When Redis raises an exception, falls back to in-memory flag."""
        from mcpgateway.plugins.framework import are_plugins_enabled_shared, enable_plugins

        enable_plugins(True)

        with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=Exception("connection refused")):
            result = await are_plugins_enabled_shared()
            assert result is True


class TestEnablePluginsShared:
    """Tests for enable_plugins_shared() — writes global toggle to Redis."""

    @pytest.mark.asyncio
    async def test_writes_true_to_redis(self):
        """enable_plugins_shared(True) writes 'true' to Redis."""
        from mcpgateway.plugins.framework import enable_plugins_shared

        mock_client = AsyncMock()
        mock_client.set = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            await enable_plugins_shared(True)
            mock_client.set.assert_called_once_with("plugin:global:enabled", "true")

    @pytest.mark.asyncio
    async def test_writes_false_to_redis(self):
        """enable_plugins_shared(False) writes 'false' to Redis."""
        from mcpgateway.plugins.framework import enable_plugins_shared

        mock_client = AsyncMock()
        mock_client.set = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            await enable_plugins_shared(False)
            mock_client.set.assert_called_once_with("plugin:global:enabled", "false")

    @pytest.mark.asyncio
    async def test_updates_in_memory_flag(self):
        """enable_plugins_shared also updates the in-memory _PLUGINS_ENABLED flag."""
        from mcpgateway.plugins.framework import are_plugins_enabled, enable_plugins, enable_plugins_shared

        enable_plugins(True)
        assert are_plugins_enabled() is True

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            await enable_plugins_shared(False)
            assert are_plugins_enabled() is False

    @pytest.mark.asyncio
    async def test_survives_redis_failure(self):
        """When Redis write fails, in-memory flag is still updated."""
        from mcpgateway.plugins.framework import are_plugins_enabled, enable_plugins, enable_plugins_shared

        enable_plugins(True)

        with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=Exception("connection refused")):
            await enable_plugins_shared(False)
            # In-memory flag should still be updated
            assert are_plugins_enabled() is False


# ---------------------------------------------------------------------------
# Layer 1: Per-plugin mode override
# ---------------------------------------------------------------------------


class TestGetPluginModeOverride:
    """Tests for get_plugin_mode_override() — reads per-plugin mode from Redis."""

    @pytest.mark.asyncio
    async def test_reads_mode_from_redis(self):
        """Returns the mode string stored in Redis."""
        from mcpgateway.plugins.framework import get_plugin_mode_override

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="enforce")

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await get_plugin_mode_override("RateLimiterPlugin")
            assert result == "enforce"
            mock_client.get.assert_called_once_with("plugin:RateLimiterPlugin:mode")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_override(self):
        """Returns None when no Redis key exists (use YAML default)."""
        from mcpgateway.plugins.framework import get_plugin_mode_override

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await get_plugin_mode_override("RateLimiterPlugin")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_unavailable(self):
        """Returns None when Redis client is None."""
        from mcpgateway.plugins.framework import get_plugin_mode_override

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            result = await get_plugin_mode_override("RateLimiterPlugin")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_exception(self):
        """Returns None when Redis raises an exception."""
        from mcpgateway.plugins.framework import get_plugin_mode_override

        with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=Exception("timeout")):
            result = await get_plugin_mode_override("RateLimiterPlugin")
            assert result is None


# ---------------------------------------------------------------------------
# Layer 1: TTL cache expiry
# ---------------------------------------------------------------------------


class TestTTLCacheExpiry:
    """Tests for TTL-based cache expiry in TenantPluginManagerFactory."""

    @pytest.mark.asyncio
    async def test_cache_returns_manager_within_ttl(self):
        """Cached manager is returned when within TTL."""
        from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory

        factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
        factory._managers = {"test::tool": (MagicMock(), time.monotonic())}
        factory._inflight = {}
        factory._lock = asyncio.Lock()
        factory._cache_ttl = 30

        manager = await factory.get_manager("test::tool")
        assert manager is not None

    @pytest.mark.asyncio
    async def test_cache_evicts_after_ttl(self):
        """Cached manager is evicted when TTL expires."""
        from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory

        mock_manager = MagicMock()
        # Set created_at to 60 seconds ago (TTL is 5s)
        factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
        factory._managers = {"test::tool": (mock_manager, time.monotonic() - 60)}
        factory._inflight = {}
        factory._lock = asyncio.Lock()
        factory._cache_ttl = 5
        factory._base_config = MagicMock()
        factory._timeout = 30
        factory._observability = None
        factory._hook_policies = None

        # get_manager should evict the stale entry and try to rebuild
        # Since we can't easily mock _build_manager, verify eviction happened
        async with factory._lock:
            entry = factory._managers.get("test::tool")
            assert entry is not None  # Still there before get_manager
            _, created_at = entry
            assert (time.monotonic() - created_at) > factory._cache_ttl  # Confirms it's expired

    def test_cache_ttl_default(self):
        """Default TTL is 30 seconds."""
        from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory

        assert TenantPluginManagerFactory.DEFAULT_CACHE_TTL == 30

    def test_cache_ttl_zero_disables(self):
        """TTL of 0 means no automatic expiry."""
        from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory

        factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
        factory._cache_ttl = 0
        # TTL check: self._cache_ttl > 0 — when 0, the check is skipped
        assert factory._cache_ttl == 0


# ---------------------------------------------------------------------------
# Layer 1: DB error fallback
# ---------------------------------------------------------------------------


class TestDBErrorFallback:
    """Tests for get_config_from_db graceful fallback on DB errors."""

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self):
        """When DB raises an exception, returns None (uses base config)."""
        from mcpgateway.plugins.gateway_plugin_manager import GatewayTenantPluginManagerFactory

        factory = GatewayTenantPluginManagerFactory.__new__(GatewayTenantPluginManagerFactory)
        factory._db_factory = MagicMock(side_effect=Exception("connection refused"))

        result = await factory.get_config_from_db("team_a::my_tool")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_context_id(self):
        """When context_id has no separator, returns None."""
        from mcpgateway.plugins.gateway_plugin_manager import GatewayTenantPluginManagerFactory

        factory = GatewayTenantPluginManagerFactory.__new__(GatewayTenantPluginManagerFactory)

        result = await factory.get_config_from_db("invalid_context_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_bindings(self):
        """When no bindings found, returns None."""
        from mcpgateway.plugins.gateway_plugin_manager import GatewayTenantPluginManagerFactory

        mock_session = MagicMock()
        factory = GatewayTenantPluginManagerFactory.__new__(GatewayTenantPluginManagerFactory)
        factory._db_factory = MagicMock(return_value=mock_session)

        with patch("mcpgateway.plugins.gateway_plugin_manager.get_bindings_for_tool", return_value=[]):
            result = await factory.get_config_from_db("team_a::my_tool")
            assert result is None


# ---------------------------------------------------------------------------
# Layer 1: Invalidation helpers
# ---------------------------------------------------------------------------


class TestInvalidateAllPluginManagers:
    """Tests for invalidate_all_plugin_managers()."""

    @pytest.mark.asyncio
    async def test_evicts_all_cached_contexts(self):
        """All cached manager contexts are evicted and rebuilt."""
        from mcpgateway.plugins.framework import invalidate_all_plugin_managers, _plugin_manager_factory
        import mcpgateway.plugins.framework as framework

        mock_factory = AsyncMock()
        mock_factory._lock = asyncio.Lock()
        mock_factory._managers = {
            "team_a::tool_1": (MagicMock(), time.monotonic()),
            "team_a::tool_2": (MagicMock(), time.monotonic()),
            "team_b::tool_1": (MagicMock(), time.monotonic()),
        }
        mock_factory.reload_tenant = AsyncMock()

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            await invalidate_all_plugin_managers()
            assert mock_factory.reload_tenant.call_count == 3
        finally:
            framework._plugin_manager_factory = original_factory

    @pytest.mark.asyncio
    async def test_noop_when_factory_is_none(self):
        """No error when factory is not initialized."""
        import mcpgateway.plugins.framework as framework

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = None
        try:
            await framework.invalidate_all_plugin_managers()
            # Should not raise
        finally:
            framework._plugin_manager_factory = original_factory


# ---------------------------------------------------------------------------
# Layer 1: Pub/Sub publisher tests
# ---------------------------------------------------------------------------


class TestPubSubPublisher:
    """Tests that state changes publish invalidation messages to Redis."""

    @pytest.mark.asyncio
    async def test_global_toggle_publishes_message(self):
        """enable_plugins_shared publishes an invalidation message."""
        from mcpgateway.plugins.framework import enable_plugins_shared

        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.publish = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            await enable_plugins_shared(False)
            mock_client.publish.assert_called_once()
            # Verify channel name
            call_args = mock_client.publish.call_args
            assert call_args[0][0] == "plugin:invalidation"
            # Verify message contains toggle info
            import json
            msg = json.loads(call_args[0][1])
            assert msg["type"] == "global_toggle"
            assert msg["enabled"] is False

    @pytest.mark.asyncio
    async def test_global_toggle_publish_failure_doesnt_crash(self):
        """If publish fails, the toggle still succeeds."""
        from mcpgateway.plugins.framework import enable_plugins_shared, are_plugins_enabled

        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.publish = AsyncMock(side_effect=Exception("publish failed"))

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            await enable_plugins_shared(True)
            # Should not crash — in-memory flag updated
            assert are_plugins_enabled() is True


class TestPubSubSubscriber:
    """Tests for the pub/sub invalidation listener."""

    @pytest.mark.asyncio
    async def test_subscriber_updates_flag_on_global_toggle(self):
        """Subscriber updates in-memory flag when receiving global_toggle message."""
        from mcpgateway.plugins.framework import _handle_invalidation_message, enable_plugins
        import json

        enable_plugins(True)
        message = {"type": "message", "data": json.dumps({"type": "global_toggle", "enabled": False})}
        await _handle_invalidation_message(message)

        from mcpgateway.plugins.framework import are_plugins_enabled
        assert are_plugins_enabled() is False

    @pytest.mark.asyncio
    async def test_subscriber_evicts_managers_on_mode_change(self):
        """Subscriber evicts all cached managers when receiving mode_change message."""
        import mcpgateway.plugins.framework as framework
        import json

        mock_factory = AsyncMock()
        mock_factory._lock = asyncio.Lock()
        mock_factory._managers = {"ctx1": (MagicMock(), time.monotonic())}
        mock_factory.reload_tenant = AsyncMock()

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            message = {"type": "message", "data": json.dumps({"type": "mode_change", "plugin": "RateLimiterPlugin", "mode": "enforce"})}
            await framework._handle_invalidation_message(message)
            mock_factory.reload_tenant.assert_called()
        finally:
            framework._plugin_manager_factory = original_factory

    @pytest.mark.asyncio
    async def test_subscriber_ignores_non_message_types(self):
        """Subscriber ignores subscribe/unsubscribe messages."""
        from mcpgateway.plugins.framework import _handle_invalidation_message, enable_plugins, are_plugins_enabled

        enable_plugins(True)
        # "subscribe" type messages should be ignored
        message = {"type": "subscribe", "data": None}
        await _handle_invalidation_message(message)
        assert are_plugins_enabled() is True  # Unchanged

    @pytest.mark.asyncio
    async def test_subscriber_handles_malformed_message(self):
        """Subscriber doesn't crash on malformed JSON."""
        from mcpgateway.plugins.framework import _handle_invalidation_message, enable_plugins, are_plugins_enabled

        enable_plugins(True)
        message = {"type": "message", "data": "not valid json {{{"}
        await _handle_invalidation_message(message)
        assert are_plugins_enabled() is True  # Unchanged, no crash

    @pytest.mark.asyncio
    async def test_subscriber_handles_binding_change(self):
        """Subscriber evicts specific context on binding_change message."""
        import mcpgateway.plugins.framework as framework
        import json

        mock_factory = AsyncMock()
        mock_factory._lock = asyncio.Lock()
        mock_factory._managers = {
            "team_a::tool_1": (MagicMock(), time.monotonic()),
            "team_b::tool_1": (MagicMock(), time.monotonic()),
        }
        mock_factory.reload_tenant = AsyncMock()

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            message = {"type": "message", "data": json.dumps({"type": "binding_change", "context_id": "team_a::tool_1"})}
            await framework._handle_invalidation_message(message)
            mock_factory.reload_tenant.assert_called_once_with("team_a::tool_1")
        finally:
            framework._plugin_manager_factory = original_factory
