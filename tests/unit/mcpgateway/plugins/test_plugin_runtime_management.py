# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_plugin_runtime_management.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for plugin runtime management.

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


def _make_bare_factory(**attrs):
    """Return a bare ``TenantPluginManagerFactory`` that skips heavy ``__init__``.

    Tests use this to exercise individual methods without loading YAML,
    creating plugin instances, or touching the DB. Pass keyword overrides to
    pre-set attributes (``_managers``, ``_cache_ttl``, etc.); sensible defaults
    are applied for the ones tests usually don't care about.
    """
    from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory

    factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
    factory._managers = attrs.get("_managers", {})
    factory._inflight = attrs.get("_inflight", {})
    factory._lock = attrs.get("_lock", asyncio.Lock())
    factory._cache_ttl = attrs.get("_cache_ttl", 30)
    factory._base_config = attrs.get("_base_config", MagicMock())
    factory._timeout = attrs.get("_timeout", 30)
    factory._observability = attrs.get("_observability", None)
    factory._hook_policies = attrs.get("_hook_policies", None)
    return factory


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
    async def test_raises_runtime_error_on_redis_exception(self):
        """Redis transport errors surface as RuntimeError so callers can distinguish them from 'no override'."""
        from mcpgateway.plugins.framework import get_plugin_mode_override

        with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=Exception("timeout")):
            with pytest.raises(RuntimeError, match="Redis client unavailable"):
                await get_plugin_mode_override("RateLimiterPlugin")


# ---------------------------------------------------------------------------
# Layer 1: TTL cache expiry
# ---------------------------------------------------------------------------


class TestTTLCacheExpiry:
    """Tests for TTL-based cache expiry in TenantPluginManagerFactory."""

    @pytest.mark.asyncio
    async def test_cache_returns_manager_within_ttl(self):
        """Cached manager is returned when within TTL."""
        from mcpgateway.plugins.framework.manager import _CachedManager

        cached = _CachedManager(manager=MagicMock(), created_at=time.monotonic())
        factory = _make_bare_factory(_managers={"test::tool": cached})

        manager = await factory.get_manager("test::tool")
        assert manager is cached.manager

    @pytest.mark.asyncio
    async def test_cache_evicts_after_ttl(self):
        """Cached manager is reported as expired once the TTL window has passed."""
        from mcpgateway.plugins.framework.manager import _CachedManager

        expired = _CachedManager(manager=MagicMock(), created_at=time.monotonic() - 60)
        factory = _make_bare_factory(_managers={"test::tool": expired}, _cache_ttl=5)

        async with factory._lock:
            entry = factory._managers.get("test::tool")
            assert entry is not None
            assert entry.is_expired(factory._cache_ttl)

    def test_cache_ttl_default(self):
        """Default TTL is 30 seconds."""
        from mcpgateway.plugins.framework.manager import TenantPluginManagerFactory

        assert TenantPluginManagerFactory.DEFAULT_CACHE_TTL == 30

    def test_cache_ttl_zero_disables(self):
        """TTL of 0 short-circuits the expiry check so entries never auto-evict."""
        from mcpgateway.plugins.framework.manager import _CachedManager

        entry = _CachedManager(manager=MagicMock(), created_at=time.monotonic() - 10_000)
        assert entry.is_expired(0) is False
        assert entry.is_expired(5) is True


class TestApplyRedisModeOverrides:
    """Direct coverage of ``_apply_redis_mode_overrides`` — the merge into ``Config``."""

    def _make_factory(self):
        # Delegate to the module-level helper so every test in the file
        # bypasses TenantPluginManagerFactory.__init__ the same way.
        return _make_bare_factory()

    def _build_config(self, plugin_names):
        """Return a lightweight stub config compatible with ``_apply_redis_mode_overrides``."""
        # Each plugin is a MagicMock that records ``model_copy`` updates.
        plugins = []
        for name in plugin_names:
            plugin = MagicMock()
            plugin.name = name
            plugin.model_copy = MagicMock(side_effect=lambda update, _name=name: SimpleNamespacePlugin(name=_name, mode=update["mode"]))
            plugins.append(plugin)
        config = MagicMock()
        config.plugins = plugins
        config.model_copy = MagicMock(side_effect=lambda update, deep: MagicMock(plugins=update["plugins"]))
        return config

    @pytest.mark.asyncio
    async def test_no_plugins_short_circuits(self):
        factory = self._make_factory()
        config = MagicMock()
        config.plugins = []
        result = await factory._apply_redis_mode_overrides(config)
        assert result is config

    @pytest.mark.asyncio
    async def test_returns_config_unchanged_when_no_overrides_in_redis(self):
        factory = self._make_factory()
        config = self._build_config(["A", "B"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[None, None])

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        assert result is config
        config.model_copy.assert_not_called()

    @pytest.mark.asyncio
    async def test_applies_per_plugin_override(self):
        factory = self._make_factory()
        config = self._build_config(["A", "B"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"disabled", None])

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        # A had its mode swapped; B was preserved as-is.
        new_plugins = result.plugins
        assert new_plugins[0].mode.value == "disabled"
        assert new_plugins[1] is config.plugins[1]

    @pytest.mark.asyncio
    async def test_corrupt_redis_falls_through_to_local_override(self):
        """A corrupt Redis value must not shadow a valid local override — both candidates are tried in priority order."""
        from mcpgateway.plugins import framework

        factory = self._make_factory()
        config = self._build_config(["A"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"garbage_mode"])

        framework._state.set_local_mode_override("A", "permissive", None)
        try:
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
                result = await factory._apply_redis_mode_overrides(config)
        finally:
            framework._state.clear_local_mode_overrides()

        # Previously the corrupt Redis value was logged then the loop fell
        # through to YAML; now it falls through to the local override.
        assert result.plugins[0].mode.value == "permissive"

    @pytest.mark.asyncio
    async def test_invalid_mode_value_skipped_not_batch_aborted(self, caplog):
        """One bad Redis value must not drop valid overrides for the rest of the batch."""
        import logging as _logging

        factory = self._make_factory()
        config = self._build_config(["A", "B"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"not_a_mode", b"enforce"])

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework.manager"):
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
                result = await factory._apply_redis_mode_overrides(config)

        # A was left alone (invalid); B was swapped — batch is NOT aborted.
        new_plugins = result.plugins
        assert new_plugins[0] is config.plugins[0]
        assert new_plugins[1].mode.value == "enforce"
        assert any("invalid Redis mode override" in rec.message.lower() or "invalid redis mode override" in rec.message.lower() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_local_override_applied_when_redis_has_nothing(self):
        """Redis-less deployments: the in-process override map drives the rebuild."""
        from mcpgateway.plugins import framework

        factory = self._make_factory()
        config = self._build_config(["A", "B"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[None, None])

        # Durable local-only entry — no expiry (Redis SET was not possible).
        framework._state.set_local_mode_override("A", "disabled", None)
        try:
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
                result = await factory._apply_redis_mode_overrides(config)
        finally:
            framework._state.clear_local_mode_overrides()

        assert result.plugins[0].mode.value == "disabled"
        assert result.plugins[1] is config.plugins[1]

    @pytest.mark.asyncio
    async def test_redis_value_beats_local_override(self):
        """When both Redis and the local map hold a value, Redis wins — cluster coordination beats local drift."""
        from mcpgateway.plugins import framework

        factory = self._make_factory()
        config = self._build_config(["A"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"enforce"])

        framework._state.set_local_mode_override("A", "disabled", None)
        try:
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
                result = await factory._apply_redis_mode_overrides(config)
        finally:
            framework._state.clear_local_mode_overrides()

        assert result.plugins[0].mode.value == "enforce"

    @pytest.mark.asyncio
    async def test_local_override_applied_when_redis_client_none(self):
        """No Redis provider at all: the in-process map is the sole source."""
        from mcpgateway.plugins import framework

        factory = self._make_factory()
        config = self._build_config(["A"])

        framework._state.set_local_mode_override("A", "permissive", None)
        try:
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
                result = await factory._apply_redis_mode_overrides(config)
        finally:
            framework._state.clear_local_mode_overrides()

        assert result.plugins[0].mode.value == "permissive"

    @pytest.mark.asyncio
    async def test_expired_redis_synced_local_override_is_pruned(self):
        """Regression pin for the "stuck past 24 h" bug: a Redis-synced entry whose TTL has elapsed must not apply."""
        from mcpgateway.plugins import framework

        factory = self._make_factory()
        config = self._build_config(["A", "B"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[None, None])

        # Entry was written when Redis was healthy (so it carries an expiry) —
        # but the expiry has already passed, matching a 24 h+ stale override.
        framework._state.set_local_mode_override("A", "disabled", time.monotonic() - 1.0)
        # Sibling durable entry that must NOT be pruned.
        framework._state.set_local_mode_override("B", "permissive", None)
        try:
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
                result = await factory._apply_redis_mode_overrides(config)
        finally:
            framework._state.clear_local_mode_overrides()

        # A expired → no override applied (YAML/config default preserved).
        assert result.plugins[0] is config.plugins[0]
        # B is durable → still applied.
        assert result.plugins[1].mode.value == "permissive"

    @pytest.mark.asyncio
    async def test_mget_failure_warns_and_returns_input(self, caplog):
        """Redis transport failures surface as WARNING — not silent DEBUG — so operators see them."""
        import logging as _logging

        factory = self._make_factory()
        config = self._build_config(["A"])

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(side_effect=Exception("EPIPE"))

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework.manager"):
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
                result = await factory._apply_redis_mode_overrides(config)

        assert result is config
        assert any(rec.levelno == _logging.WARNING for rec in caplog.records)


class SimpleNamespacePlugin:
    """Tiny stand-in plugin with a mode-carrying enum attribute."""

    def __init__(self, name, mode):
        from mcpgateway.plugins.framework.models import PluginMode

        self.name = name
        self.mode = mode if isinstance(mode, PluginMode) else PluginMode(mode)


# ---------------------------------------------------------------------------
# Layer 1: DB error fallback
# ---------------------------------------------------------------------------


class TestDBErrorFallback:
    """Tests for get_config_from_db graceful fallback on DB errors."""

    @pytest.mark.asyncio
    async def test_raises_on_db_error(self):
        """DB failures must raise so the rebuild fails loudly — silently falling back to YAML drops security-relevant overrides."""
        from mcpgateway.plugins.gateway_plugin_manager import GatewayTenantPluginManagerFactory

        factory = GatewayTenantPluginManagerFactory.__new__(GatewayTenantPluginManagerFactory)
        factory._db_factory = MagicMock(side_effect=Exception("connection refused"))

        with pytest.raises(Exception, match="connection refused"):
            await factory.get_config_from_db("team_a::my_tool")

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
    async def test_delegates_to_factory_invalidate_all(self):
        """Module helper routes through ``factory.invalidate_all()`` rather than reaching into private state."""
        from mcpgateway.plugins.framework import invalidate_all_plugin_managers
        from mcpgateway.plugins import framework

        mock_factory = AsyncMock()
        mock_factory.invalidate_all = AsyncMock()

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            await invalidate_all_plugin_managers()
            mock_factory.invalidate_all.assert_awaited_once()
        finally:
            framework._plugin_manager_factory = original_factory

    @pytest.mark.asyncio
    async def test_noop_when_factory_is_none(self):
        """No error when factory is not initialized."""
        from mcpgateway.plugins import framework

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
        """Subscriber triggers factory-wide invalidation when a mode_change frame arrives."""
        from mcpgateway.plugins import framework
        import json

        mock_factory = AsyncMock()
        mock_factory.invalidate_all = AsyncMock()

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            message = {"type": "message", "data": json.dumps({"type": "mode_change", "plugin": "RateLimiterPlugin", "mode": "enforce"})}
            await framework._handle_invalidation_message(message)
            mock_factory.invalidate_all.assert_awaited()
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


class TestPublishHelpers:
    """Tests that the publish helpers emit correctly-shaped invalidation messages."""

    @pytest.mark.asyncio
    async def test_publish_plugin_mode_change_sends_mode_change_message(self):
        """publish_plugin_mode_change must SET the key AND publish a mode_change frame."""
        import json
        from mcpgateway.plugins.framework import publish_plugin_mode_change

        client = AsyncMock()
        client.set = AsyncMock()
        client.publish = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
            ok = await publish_plugin_mode_change("RateLimiterPlugin", "enforce")

        assert ok is True
        # SET carries the 24h TTL
        set_call = client.set.call_args
        assert set_call.args[:2] == ("plugin:RateLimiterPlugin:mode", "enforce")
        assert set_call.kwargs.get("ex") == 86400
        # PUBLISH hits the right channel with the right discriminator, plus
        # ttl_seconds so every peer stamps the same absolute deadline.
        pub_call = client.publish.call_args
        assert pub_call.args[0] == "plugin:invalidation"
        msg = json.loads(pub_call.args[1])
        assert msg == {"type": "mode_change", "plugin": "RateLimiterPlugin", "mode": "enforce", "ttl_seconds": 86400}

    @pytest.mark.asyncio
    async def test_publish_plugin_mode_change_returns_false_on_set_failure(self):
        """A SET transport failure must surface as False so the caller signals the outage."""
        from mcpgateway.plugins.framework import publish_plugin_mode_change

        client = AsyncMock()
        client.set = AsyncMock(side_effect=Exception("ECONNREFUSED"))
        client.publish = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
            ok = await publish_plugin_mode_change("RateLimiterPlugin", "enforce")

        assert ok is False
        client.publish.assert_not_awaited()  # No half-state broadcast

    @pytest.mark.asyncio
    async def test_local_entry_expiry_aligns_with_redis_ttl_on_success(self):
        """Redis-synced local entries must carry a ~24 h monotonic expiry — otherwise they'd outlive the Redis key."""
        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import publish_plugin_mode_change

        client = AsyncMock()
        client.set = AsyncMock()
        client.publish = AsyncMock()

        before = time.monotonic()
        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
            ok = await publish_plugin_mode_change("RateLimiterPlugin", "enforce")
        after = time.monotonic()

        assert ok is True
        entry = framework._state.get_local_mode_overrides_live()["RateLimiterPlugin"]
        mode, expires_at = entry
        assert mode == "enforce"
        assert expires_at is not None
        # Tolerance accounts for the monotonic tick between before/after.
        assert before + 86400 <= expires_at <= after + 86400

    @pytest.mark.asyncio
    async def test_local_entry_has_no_expiry_when_redis_set_fails(self):
        """Local-only entries (Redis SET failed) must be durable — the operator never got confirmation the timer started."""
        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import publish_plugin_mode_change

        client = AsyncMock()
        client.set = AsyncMock(side_effect=Exception("ECONNREFUSED"))
        client.publish = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
            ok = await publish_plugin_mode_change("RateLimiterPlugin", "enforce")

        assert ok is False
        entry = framework._state.get_local_mode_overrides_live()["RateLimiterPlugin"]
        mode, expires_at = entry
        assert mode == "enforce"
        assert expires_at is None

    @pytest.mark.asyncio
    async def test_publish_binding_change_sends_binding_change_message(self):
        """publish_binding_change must emit a binding_change frame with the context id."""
        import json
        from mcpgateway.plugins.framework import publish_binding_change

        client = AsyncMock()
        client.publish = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
            ok = await publish_binding_change("team_a::my_tool")

        assert ok is True
        pub_call = client.publish.call_args
        assert pub_call.args[0] == "plugin:invalidation"
        msg = json.loads(pub_call.args[1])
        assert msg == {"type": "binding_change", "context_id": "team_a::my_tool"}


class TestPublishToListenerRoundTrip:
    """End-to-end: one side publishes; the handler on another worker dispatches."""

    @pytest.mark.asyncio
    async def test_mode_change_publish_triggers_factory_invalidate(self):
        """Publishing a mode_change must cause the listener handler to trigger cluster-wide invalidation."""
        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import _handle_invalidation_message, publish_plugin_mode_change

        # Simulate the local factory on the *listener* side. Module helper routes
        # through ``factory.invalidate_all()``, so we just assert that was awaited.
        mock_factory = AsyncMock()
        mock_factory.invalidate_all = AsyncMock()

        # Capture the published frame; feed it back into _handle_invalidation_message
        # to mimic the Redis pub/sub round-trip on a peer worker.
        published = {}

        async def _fake_publish(channel, payload):
            published["channel"] = channel
            published["payload"] = payload

        client = AsyncMock()
        client.set = AsyncMock()
        client.publish = AsyncMock(side_effect=_fake_publish)

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
                await publish_plugin_mode_change("RateLimiterPlugin", "enforce")

            assert published["channel"] == "plugin:invalidation"
            frame = {"type": "message", "data": published["payload"]}
            await _handle_invalidation_message(frame)

            # Listener-side handler delegates to the factory's public invalidate_all.
            mock_factory.invalidate_all.assert_awaited_once()
        finally:
            framework._plugin_manager_factory = original_factory

    @pytest.mark.asyncio
    async def test_global_toggle_pubsub_invalidates_local_cache(self):
        """A global_toggle broadcast must drop the short-lived local cache, not just update the flag."""
        import json
        from mcpgateway.plugins.framework import _handle_invalidation_message, are_plugins_enabled_shared, enable_plugins

        enable_plugins(True)
        # Prime the local cache with True.
        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            assert await are_plugins_enabled_shared() is True

        # Broadcast flips the toggle OFF.
        await _handle_invalidation_message({"type": "message", "data": json.dumps({"type": "global_toggle", "enabled": False})})

        # Next read must NOT serve the cached True — it must reflect the new state.
        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            assert await are_plugins_enabled_shared() is False


class TestFactoryInvalidateTeam:
    """Public ``invalidate_team`` replaces tool_plugin_bindings reaching into private state."""

    @pytest.mark.asyncio
    async def test_invalidates_only_matching_team(self):
        from mcpgateway.plugins.framework.manager import _CachedManager

        factory = _make_bare_factory(
            _managers={
                "team_a::tool_1": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
                "team_a::tool_2": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
                "team_b::tool_1": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
                "__global__": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
            }
        )
        factory.reload_tenant = AsyncMock()

        await factory.invalidate_team("team_a", "::")

        # Only the two team_a entries should have been reloaded.
        calls = [c.args[0] for c in factory.reload_tenant.call_args_list]
        assert set(calls) == {"team_a::tool_1", "team_a::tool_2"}

    @pytest.mark.asyncio
    async def test_uses_class_separator_when_not_specified(self):
        """Default separator is ``CONTEXT_ID_SEPARATOR`` — saves the listener from knowing it on the wire."""
        from mcpgateway.plugins.framework.manager import _CachedManager

        factory = _make_bare_factory(
            _managers={
                "team_a::tool_1": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
                "team_a-other::tool_1": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
            }
        )
        factory.reload_tenant = AsyncMock()

        await factory.invalidate_team("team_a")  # no separator arg → uses CONTEXT_ID_SEPARATOR

        calls = [c.args[0] for c in factory.reload_tenant.call_args_list]
        # Only the context that starts with "team_a::" — not "team_a-other::".
        assert set(calls) == {"team_a::tool_1"}


class TestTeamBindingChangeRoundTrip:
    """Regression pin: wildcard bindings must evict every per-tool cache in the cluster, not just ``team::*``."""

    @pytest.mark.asyncio
    async def test_publish_team_binding_change_emits_correct_frame(self):
        import json

        from mcpgateway.plugins.framework import publish_team_binding_change

        client = AsyncMock()
        client.publish = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
            ok = await publish_team_binding_change("team_a")

        assert ok is True
        pub_call = client.publish.call_args
        assert pub_call.args[0] == "plugin:invalidation"
        msg = json.loads(pub_call.args[1])
        assert msg == {"type": "team_binding_change", "team_id": "team_a"}

    @pytest.mark.asyncio
    async def test_handler_evicts_every_per_tool_context_for_team(self):
        """A team_binding_change frame on a remote worker must reload every ``team_a::*`` cache entry."""
        import json

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import _handle_invalidation_message
        from mcpgateway.plugins.framework.manager import _CachedManager

        factory = _make_bare_factory(
            _managers={
                "team_a::tool_1": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
                "team_a::tool_2": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
                "team_b::tool_1": _CachedManager(manager=MagicMock(), created_at=time.monotonic()),
            }
        )
        factory.reload_tenant = AsyncMock()

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = factory
        try:
            frame = {"type": "message", "data": json.dumps({"type": "team_binding_change", "team_id": "team_a"})}
            await _handle_invalidation_message(frame)
        finally:
            framework._plugin_manager_factory = original_factory

        calls = [c.args[0] for c in factory.reload_tenant.call_args_list]
        assert set(calls) == {"team_a::tool_1", "team_a::tool_2"}  # team_b left alone


class TestSubscriberHandlesBindingChange:
    """Lift of the original binding_change test (kept for backwards compatibility after the refactor)."""

    @pytest.mark.asyncio
    async def test_subscriber_handles_binding_change(self):
        """Subscriber evicts specific context on binding_change message."""
        from mcpgateway.plugins import framework
        import json

        mock_factory = AsyncMock()
        mock_factory.reload_tenant = AsyncMock()

        original_factory = framework._plugin_manager_factory
        framework._plugin_manager_factory = mock_factory
        try:
            message = {"type": "message", "data": json.dumps({"type": "binding_change", "context_id": "team_a::tool_1"})}
            await framework._handle_invalidation_message(message)
            mock_factory.reload_tenant.assert_called_once_with("team_a::tool_1")
        finally:
            framework._plugin_manager_factory = original_factory


class TestListenerLocalMirror:
    """Pin the side-effect: mode_change broadcasts must populate the local override map."""

    @pytest.mark.asyncio
    async def test_mode_change_populates_local_map_with_broadcast_ttl(self):
        """The handler stamps ``(mode, monotonic + ttl_seconds)`` using the publisher's TTL, not a local constant."""
        import json

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import _handle_invalidation_message

        # No factory needed for this assertion; invalidate_all is a no-op.
        framework._state.clear_local_mode_overrides()
        before = time.monotonic()
        await _handle_invalidation_message({"type": "message", "data": json.dumps({"type": "mode_change", "plugin": "Foo", "mode": "enforce", "ttl_seconds": 600})})
        after = time.monotonic()

        entry = framework._state.get_local_mode_overrides_live()["Foo"]
        mode, expires_at = entry
        assert mode == "enforce"
        assert expires_at is not None
        # Peer uses the broadcast's ttl_seconds, not the 24h local constant.
        assert before + 600 <= expires_at <= after + 600

    @pytest.mark.asyncio
    async def test_mode_change_falls_back_to_default_ttl_without_field(self):
        """Older publishers that omit ``ttl_seconds`` fall back to the 24 h default."""
        import json

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import _handle_invalidation_message

        framework._state.clear_local_mode_overrides()
        before = time.monotonic()
        await _handle_invalidation_message({"type": "message", "data": json.dumps({"type": "mode_change", "plugin": "Foo", "mode": "enforce"})})
        after = time.monotonic()

        _, expires_at = framework._state.get_local_mode_overrides_live()["Foo"]
        assert expires_at is not None
        assert before + 86400 <= expires_at <= after + 86400

    def test_backing_dict_identity_is_stable(self):
        """Regression pin: writers and readers must share one dict object — introducing a copy would split the listener from the manager."""
        from mcpgateway.plugins.framework import _state

        first = _state.get_local_mode_overrides_live()
        _state.set_local_mode_override("Identity", "enforce", None)
        assert _state.get_local_mode_overrides_live() is first


class TestListenerStartup:
    """Regression pins for ``start_plugin_invalidation_listener`` — TOCTOU lock and skip-when-no-provider."""

    @pytest.mark.asyncio
    async def test_skips_start_when_no_redis_provider(self, caplog):
        """Single-node deployments without a Redis provider must not create the listener task."""
        import logging as _logging

        from mcpgateway.plugins.framework import start_plugin_invalidation_listener, stop_plugin_invalidation_listener
        from mcpgateway.plugins.framework._redis import set_shared_redis_provider

        set_shared_redis_provider(None)
        from mcpgateway.plugins import framework

        framework._pubsub_task = None

        with caplog.at_level(_logging.INFO, logger="mcpgateway.plugins.framework"):
            await start_plugin_invalidation_listener()

        assert framework._pubsub_task is None
        assert any("no Redis provider" in rec.message for rec in caplog.records)
        await stop_plugin_invalidation_listener()

    @pytest.mark.asyncio
    async def test_concurrent_starts_only_create_one_task(self, monkeypatch):
        """Two racing callers must not both reach ``asyncio.create_task`` (TOCTOU guard)."""
        from mcpgateway.plugins.framework import start_plugin_invalidation_listener, stop_plugin_invalidation_listener
        from mcpgateway.plugins import framework

        framework._pubsub_task = None

        # _redis() returns a dummy non-None client. The listener task itself
        # will raise almost immediately when it tries pubsub() on the dummy,
        # but that happens inside the task — start_plugin_invalidation_listener
        # only cares about the create-task path.
        dummy_client = MagicMock()
        monkeypatch.setattr(framework, "_redis", AsyncMock(return_value=dummy_client))

        await asyncio.gather(
            start_plugin_invalidation_listener(),
            start_plugin_invalidation_listener(),
            start_plugin_invalidation_listener(),
        )

        assert framework._pubsub_task is not None
        await stop_plugin_invalidation_listener()
        assert framework._pubsub_task is None

    @pytest.mark.asyncio
    async def test_probe_failure_does_not_start_and_logs(self, monkeypatch, caplog):
        """If the Redis probe raises, the listener must not start and the failure must log at WARNING."""
        import logging as _logging

        from mcpgateway.plugins.framework import start_plugin_invalidation_listener, stop_plugin_invalidation_listener
        from mcpgateway.plugins import framework

        framework._pubsub_task = None
        monkeypatch.setattr(framework, "_redis", AsyncMock(side_effect=RuntimeError("probe blew up")))

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework"):
            await start_plugin_invalidation_listener()

        assert framework._pubsub_task is None
        assert any("probe failed" in rec.message for rec in caplog.records)
        await stop_plugin_invalidation_listener()


class TestPublishPartialWriteSignaling:
    """When Redis SET succeeded but the broadcast failed, operators see an ERROR log."""

    @pytest.mark.asyncio
    async def test_enable_plugins_shared_errors_on_publish_failure(self, caplog):
        import logging as _logging

        from mcpgateway.plugins.framework import enable_plugins_shared

        client = AsyncMock()
        client.set = AsyncMock()
        client.publish = AsyncMock(side_effect=Exception("broker down"))

        with caplog.at_level(_logging.ERROR, logger="mcpgateway.plugins.framework"):
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
                await enable_plugins_shared(True)

        assert any("broadcast failed" in rec.message and rec.levelno == _logging.ERROR for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_publish_plugin_mode_change_errors_on_publish_failure(self, caplog):
        import logging as _logging

        from mcpgateway.plugins.framework import publish_plugin_mode_change

        client = AsyncMock()
        client.set = AsyncMock()
        client.publish = AsyncMock(side_effect=Exception("broker down"))

        with caplog.at_level(_logging.ERROR, logger="mcpgateway.plugins.framework"):
            with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=client):
                await publish_plugin_mode_change("Foo", "enforce")

        assert any("broadcast failed" in rec.message and rec.levelno == _logging.ERROR for rec in caplog.records)


class TestFactoryInitFailureSurface:
    """``init_plugin_manager_factory`` must surface config errors so the lifespan can decide to hard-crash.

    Pins the contract that ``main.py`` relies on: if the YAML load or Pydantic
    validation fails, the exception propagates. A refactor that silently
    absorbs it would re-introduce the "gateway boots with plugins silently
    dead" bug that prompted commit ``268915089``.

    Note: missing-file is deliberately swallowed by ``ConfigLoader.load_config``
    (minimal-environment fallback), so we pin only the cases the lifespan
    actually needs to see — malformed YAML and invalid config shape.
    """

    def test_malformed_yaml_raises(self, tmp_path):
        from mcpgateway.plugins.framework import init_plugin_manager_factory

        bad = tmp_path / "bad.yaml"
        bad.write_text("plugins: [this is not a valid plugin list:::")

        with pytest.raises(Exception):
            init_plugin_manager_factory(
                yaml_path=str(bad),
                timeout=30,
                hook_policies={},
                observability=None,
                db_factory=None,
            )

    def test_invalid_config_shape_raises(self, tmp_path):
        from mcpgateway.plugins.framework import init_plugin_manager_factory

        bad = tmp_path / "bad.yaml"
        # plugin_settings.plugin_timeout must be an int per the Config schema.
        bad.write_text("plugin_settings:\n  plugin_timeout: not-a-number\nplugins: []\n")

        with pytest.raises(Exception):
            init_plugin_manager_factory(
                yaml_path=str(bad),
                timeout=30,
                hook_policies={},
                observability=None,
                db_factory=None,
            )


class TestFactoryInitDegradedSignal:
    """When plugins.enabled=false + init fails, the node must log once when the toggle later asks it to serve."""

    @pytest.mark.asyncio
    async def test_get_plugin_manager_emits_error_once_on_degraded_node(self, caplog):
        import logging as _logging

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import (
            _reset_factory_init_degraded_for_tests,
            enable_plugins,
            get_plugin_manager,
            mark_factory_init_degraded,
        )

        _reset_factory_init_degraded_for_tests()
        framework._plugin_manager_factory = None
        enable_plugins(True)  # Seed in-memory flag so are_plugins_enabled_shared() returns True.
        mark_factory_init_degraded()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            with caplog.at_level(_logging.ERROR, logger="mcpgateway.plugins.framework"):
                assert await get_plugin_manager() is None
                assert await get_plugin_manager() is None

        degraded_errors = [rec for rec in caplog.records if rec.levelno == _logging.ERROR and "factory init failed" in rec.message]
        # One ERROR, not one per request.
        assert len(degraded_errors) == 1, f"expected 1 ERROR, got {len(degraded_errors)}: {[r.message for r in degraded_errors]}"

    @pytest.mark.asyncio
    async def test_no_error_when_factory_is_initialized(self, caplog):
        """A healthy node never emits the degraded-boot ERROR."""
        import logging as _logging

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import enable_plugins, get_plugin_manager

        mock_factory = AsyncMock()
        mock_factory.get_manager = AsyncMock(return_value=MagicMock())
        framework._plugin_manager_factory = mock_factory
        enable_plugins(True)

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            with caplog.at_level(_logging.ERROR, logger="mcpgateway.plugins.framework"):
                await get_plugin_manager()

        assert not any("factory init failed" in rec.message for rec in caplog.records)
        framework._plugin_manager_factory = None

    @pytest.mark.asyncio
    async def test_no_error_when_toggle_is_off(self, caplog):
        """Degraded node with the shared toggle off must stay quiet — the opt-out is doing its job."""
        import logging as _logging

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import (
            enable_plugins,
            get_plugin_manager,
            mark_factory_init_degraded,
        )

        framework._plugin_manager_factory = None
        enable_plugins(False)  # toggle off
        mark_factory_init_degraded()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            with caplog.at_level(_logging.ERROR, logger="mcpgateway.plugins.framework"):
                await get_plugin_manager()

        assert not any("factory init failed" in rec.message for rec in caplog.records)


class TestListenerBackoff:
    """Regression pins for ``_plugin_invalidation_listener`` reconnect loop."""

    @pytest.mark.asyncio
    async def test_escalates_to_error_after_five_consecutive_failures(self, monkeypatch, caplog):
        """Exponential backoff plus ERROR log after 5 failures keeps ops visibility when Redis is flaky."""
        import logging as _logging

        from mcpgateway.plugins import framework

        # Force every subscribe attempt to raise, so the backoff loop cycles.
        async def _always_raises():
            raise RuntimeError("redis broker unavailable")

        monkeypatch.setattr(framework, "_redis", _always_raises)

        # Neutralise actual sleeping — just count calls and cap iterations.
        sleeps: list[float] = []

        async def _fake_sleep(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) >= 6:
                raise asyncio.CancelledError()

        monkeypatch.setattr(framework.asyncio, "sleep", _fake_sleep)

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework"):
            try:
                await framework._plugin_invalidation_listener()
            except asyncio.CancelledError:
                pass

        # First 4 failures at WARNING; failure #5 onward at ERROR.
        warnings = [r for r in caplog.records if r.levelno == _logging.WARNING and "reconnecting" in r.message]
        errors = [r for r in caplog.records if r.levelno == _logging.ERROR and "reconnecting" in r.message]
        assert len(warnings) == 4, f"expected 4 WARNING-level failures before escalation, got {len(warnings)}"
        assert len(errors) >= 1, "expected ERROR-level logs after the 5th consecutive failure"

        # Backoff must be non-decreasing up to the 30 s cap.
        assert all(d <= 30.0 + 1e-6 for d in sleeps), f"backoff exceeded 30s cap: {sleeps}"
        assert sleeps[-1] >= sleeps[0], f"backoff must grow, not shrink: {sleeps}"


class TestFactoryGetManagerBranches:
    """Narrow pins on the ``TenantPluginManagerFactory.get_manager`` caching branches."""

    @pytest.mark.asyncio
    async def test_cache_ttl_expiry_evicts_and_rebuilds(self):
        """An expired cache entry must be popped and re-built, not served stale."""
        from mcpgateway.plugins.framework.manager import _CachedManager

        factory = _make_bare_factory(_cache_ttl=0.001)
        stale = MagicMock(name="stale_manager")
        factory._managers["ctx-1"] = _CachedManager(manager=stale, created_at=time.monotonic() - 10)

        fresh = MagicMock(name="fresh_manager")
        build_calls: list[str] = []

        async def _fake_build(ctx):
            build_calls.append(ctx)
            return fresh

        factory._build_manager = _fake_build
        result = await factory.get_manager("ctx-1")
        # Expired entry forced a rebuild (covers the TTL-eviction branch).
        assert build_calls == ["ctx-1"]
        assert result is fresh, "expected the rebuilt manager, got the stale cached one"

    @pytest.mark.asyncio
    async def test_apply_redis_mode_overrides_handles_client_exception(self, caplog):
        """A client-factory exception logs a WARNING and falls through to YAML defaults (no override applied)."""
        import logging as _logging

        factory = _make_bare_factory()
        # Build a minimal Config-like object with a single plugin.
        plugin = MagicMock()
        plugin.name = "A"
        plugin.mode = MagicMock()
        plugin.model_copy = MagicMock(side_effect=AssertionError("must not be called — no override to apply"))
        config = MagicMock()
        config.plugins = [plugin]

        with patch("mcpgateway.plugins.framework._redis.get_shared_redis_client", side_effect=RuntimeError("no client")):
            with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework.manager"):
                result = await factory._apply_redis_mode_overrides(config)

        # Config is returned unchanged (no model_copy invoked).
        assert result is config
        assert any("client error" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_apply_redis_mode_overrides_skips_override_on_validation_error(self, caplog):
        """``plugin.model_copy`` raising ``ValidationError`` logs a WARNING and leaves the plugin untouched."""
        import logging as _logging

        from pydantic import ValidationError as _PydValidationError
        from mcpgateway.plugins.framework import PluginMode

        factory = _make_bare_factory()
        plugin = MagicMock()
        plugin.name = "A"
        plugin.mode = PluginMode.ENFORCE

        def _raise_validation(*_a, **_k):
            raise _PydValidationError.from_exception_data("bad", [])

        plugin.model_copy = MagicMock(side_effect=_raise_validation)
        config = MagicMock()
        config.plugins = [plugin]

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"permissive"])

        with patch("mcpgateway.plugins.framework._redis.get_shared_redis_client", return_value=mock_client):
            with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework.manager"):
                result = await factory._apply_redis_mode_overrides(config)

        # Config is returned unchanged because the one override failed validation.
        assert result is config
        assert any("validation failed" in rec.message for rec in caplog.records)


class TestInvalidateHelpers:
    """Pins for ``invalidate_all``/``invalidate_team`` swallow-and-log semantics and ``iter_context_ids``."""

    @pytest.mark.asyncio
    async def test_invalidate_all_logs_when_reload_raises(self, caplog):
        """One reload failure must not abort the sweep — it logs and moves on."""
        import logging as _logging

        from mcpgateway.plugins.framework.manager import _CachedManager

        factory = _make_bare_factory()
        factory._managers["ctx-a"] = _CachedManager(manager=MagicMock(), created_at=time.monotonic())
        factory.reload_tenant = AsyncMock(side_effect=RuntimeError("reload blew up"))

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework.manager"):
            await factory.invalidate_all()

        assert any("invalidate_all: reload failed" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_invalidate_team_logs_when_reload_raises(self, caplog):
        """Same guarantee on the team-scoped sweep."""
        import logging as _logging

        from mcpgateway.plugins.framework.manager import _CachedManager

        factory = _make_bare_factory()
        factory.CONTEXT_ID_SEPARATOR = "::"
        factory._managers["team-a::tool-1"] = _CachedManager(manager=MagicMock(), created_at=time.monotonic())
        factory.reload_tenant = AsyncMock(side_effect=RuntimeError("reload blew up"))

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework.manager"):
            await factory.invalidate_team("team-a")

        assert any("invalidate_team: reload failed" in rec.message for rec in caplog.records)

    def test_iter_context_ids_returns_snapshot_list(self):
        """``iter_context_ids`` copies the cache keys so callers iterating without the lock are safe."""
        from mcpgateway.plugins.framework.manager import _CachedManager

        factory = _make_bare_factory()
        factory._managers["ctx-a"] = _CachedManager(manager=MagicMock(), created_at=time.monotonic())
        factory._managers["ctx-b"] = _CachedManager(manager=MagicMock(), created_at=time.monotonic())

        snapshot = factory.iter_context_ids()
        # Snapshot, not a live view — mutating the cache afterwards shouldn't touch the prior read.
        factory._managers["ctx-c"] = _CachedManager(manager=MagicMock(), created_at=time.monotonic())
        assert set(snapshot) == {"ctx-a", "ctx-b"}


class TestRedisExceptionBranches:
    """Narrow tests for the Redis-transport failure branches."""

    @pytest.mark.asyncio
    async def test_read_shared_enabled_falls_back_on_client_get_exception(self):
        """When ``client.get`` raises, ``_read_shared_enabled`` falls back to the in-memory flag."""
        from mcpgateway.plugins.framework import _read_shared_enabled, enable_plugins

        enable_plugins(True)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("broken pipe"))

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            result = await _read_shared_enabled()
            assert result is True

    @pytest.mark.asyncio
    async def test_enable_plugins_shared_returns_false_on_set_exception(self):
        """A Redis SET that raises is downgraded to a local-only toggle change."""
        from mcpgateway.plugins.framework import enable_plugins_shared, are_plugins_enabled

        mock_client = AsyncMock()
        mock_client.set = AsyncMock(side_effect=RuntimeError("ECONNRESET"))
        mock_client.publish = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            ok = await enable_plugins_shared(True)

        assert ok is False
        # In-memory flag is still updated even when the Redis write blew up.
        assert are_plugins_enabled() is True

    @pytest.mark.asyncio
    async def test_publish_invalidation_returns_false_on_client_error(self, monkeypatch):
        """When the Redis client factory itself raises, publish bails at False."""
        from mcpgateway.plugins import framework

        async def _always_raises():
            raise RuntimeError("no redis")

        monkeypatch.setattr(framework, "_redis", _always_raises)
        # pylint: disable=protected-access
        result = await framework._publish_invalidation({"type": "global_toggle", "enabled": True})
        assert result is False

    @pytest.mark.asyncio
    async def test_publish_plugin_mode_change_redis_client_exception(self, monkeypatch):
        """``_redis()`` failure still stamps the local override so the worker honours the change."""
        from mcpgateway.plugins import framework

        async def _always_raises():
            raise RuntimeError("no redis")

        monkeypatch.setattr(framework, "_redis", _always_raises)
        framework._state.clear_local_mode_overrides()

        ok = await framework.publish_plugin_mode_change("Foo", "enforce")
        assert ok is False
        mode, expires_at = framework._state.get_local_mode_overrides_live()["Foo"]
        assert mode == "enforce"
        # Local-only entries are durable (no expiry) — the operator never saw
        # confirmation that the 24h TTL clock started.
        assert expires_at is None
        framework._state.clear_local_mode_overrides()

    @pytest.mark.asyncio
    async def test_get_plugin_mode_override_raises_on_client_get_exception(self):
        """``client.get`` blowing up surfaces as ``RuntimeError`` so callers see "Redis unreachable"."""
        from mcpgateway.plugins.framework import get_plugin_mode_override

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Redis GET failed"):
                await get_plugin_mode_override("Foo")


class TestFactoryAccessors:
    """Pins on accessors whose non-trivial branches weren't otherwise exercised."""

    def test_get_plugin_manager_factory_returns_live_factory(self):
        """When a factory is set, the accessor returns it rather than ``None``."""
        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import get_plugin_manager_factory, reset_plugin_manager_factory

        sentinel = MagicMock(name="sentinel-factory")
        framework._plugin_manager_factory = sentinel
        try:
            assert get_plugin_manager_factory() is sentinel
        finally:
            reset_plugin_manager_factory()

    def test_list_configured_plugin_names_returns_config_names(self):
        """With a live factory whose ``_base_config`` has plugins, the helper returns their names."""
        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import list_configured_plugin_names, reset_plugin_manager_factory

        fake_factory = MagicMock()
        fake_factory._base_config = MagicMock()
        fake_factory._base_config.plugins = [MagicMock(name="P1"), MagicMock(name="P2")]
        fake_factory._base_config.plugins[0].name = "PluginOne"
        fake_factory._base_config.plugins[1].name = "PluginTwo"

        framework._plugin_manager_factory = fake_factory
        try:
            assert list_configured_plugin_names() == ["PluginOne", "PluginTwo"]
        finally:
            reset_plugin_manager_factory()

    def test_list_configured_plugin_names_empty_without_factory(self):
        """No factory yet → empty list (covers the early-return branch)."""
        from mcpgateway.plugins.framework import list_configured_plugin_names, reset_plugin_manager_factory

        reset_plugin_manager_factory()
        assert list_configured_plugin_names() == []

    def test_list_configured_plugin_names_empty_when_config_has_no_plugins(self):
        """Factory present but empty ``plugins`` → empty list (guards the ``not config.plugins`` branch)."""
        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import list_configured_plugin_names, reset_plugin_manager_factory

        fake_factory = MagicMock()
        fake_factory._base_config = MagicMock()
        fake_factory._base_config.plugins = []

        framework._plugin_manager_factory = fake_factory
        try:
            assert list_configured_plugin_names() == []
        finally:
            reset_plugin_manager_factory()


class TestInitPluginManagerFactory:
    """Cover the ``db_factory``-branch in ``init_plugin_manager_factory``."""

    def test_uses_gateway_factory_when_db_factory_provided(self, monkeypatch):
        """Passing a ``db_factory`` must route through ``GatewayTenantPluginManagerFactory``."""
        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import init_plugin_manager_factory, reset_plugin_manager_factory

        captured_kwargs: dict = {}

        class _FakeGatewayFactory:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

        # Patch the lazy import site so the constructor call is our spy.
        monkeypatch.setattr(
            "mcpgateway.plugins.gateway_plugin_manager.GatewayTenantPluginManagerFactory",
            _FakeGatewayFactory,
        )

        def _fake_session_local():
            return MagicMock(name="Session")

        reset_plugin_manager_factory()
        try:
            init_plugin_manager_factory(
                yaml_path="does/not/matter.yaml",
                timeout=30.0,
                hook_policies={},
                observability=None,
                db_factory=_fake_session_local,
            )
            assert isinstance(framework._plugin_manager_factory, _FakeGatewayFactory)
            assert captured_kwargs["yaml_path"] == "does/not/matter.yaml"
            assert captured_kwargs["db_factory"] is _fake_session_local
        finally:
            reset_plugin_manager_factory()


class TestListenerMessageValidation:
    """Listener robustness: malformed/unknown frames must be dropped without crashing the loop."""

    @pytest.mark.asyncio
    async def test_handle_invalidation_message_drops_unknown_frame(self, caplog):
        """A frame whose ``type`` doesn't match any discriminator is logged and ignored."""
        import logging as _logging
        import json as _json

        from mcpgateway.plugins.framework import _handle_invalidation_message

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework"):
            await _handle_invalidation_message({"type": "message", "data": _json.dumps({"type": "bogus_event", "payload": 1})})

        assert any("unrecognised plugin invalidation frame" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_handle_invalidation_team_binding_logs_when_invalidate_team_raises(self, monkeypatch, caplog):
        """Invalidate-team failure during pub/sub must be logged (not raised) so the listener loop survives."""
        import logging as _logging
        import json as _json

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import _handle_invalidation_message

        fake_factory = MagicMock()
        fake_factory.invalidate_team = AsyncMock(side_effect=RuntimeError("cache busted"))
        monkeypatch.setattr(framework, "_plugin_manager_factory", fake_factory)

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework"):
            await _handle_invalidation_message({"type": "message", "data": _json.dumps({"type": "team_binding_change", "team_id": "team-a"})})

        assert any("team_binding_change failed" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_handle_invalidation_binding_change_logs_when_reload_raises(self, monkeypatch, caplog):
        """Reload-tenant failure during pub/sub must be logged (not raised)."""
        import logging as _logging
        import json as _json

        from mcpgateway.plugins import framework
        from mcpgateway.plugins.framework import _handle_invalidation_message

        fake_factory = MagicMock()
        fake_factory.reload_tenant = AsyncMock(side_effect=RuntimeError("cache busted"))
        monkeypatch.setattr(framework, "_plugin_manager_factory", fake_factory)

        with caplog.at_level(_logging.WARNING, logger="mcpgateway.plugins.framework"):
            await _handle_invalidation_message({"type": "message", "data": _json.dumps({"type": "binding_change", "context_id": "ctx-a"})})

        assert any("binding_change reload failed" in rec.message for rec in caplog.records)


class TestListenerLoopBranches:
    """Cover the happy subscribe/listen path and the Redis-unavailable polling path."""

    @pytest.mark.asyncio
    async def test_listener_polls_when_redis_client_is_none(self, monkeypatch):
        """When ``_redis()`` returns None, the listener sleeps and retries instead of spinning.

        The listener's ``except asyncio.CancelledError`` branch breaks out of
        the loop cleanly, so the coroutine returns rather than propagating —
        we verify the polling sleep was hit at least once.
        """
        from mcpgateway.plugins import framework

        monkeypatch.setattr(framework, "_redis", AsyncMock(return_value=None))

        slept: list[float] = []

        async def _fake_sleep(delay):
            slept.append(delay)
            # Let the first iteration hit ``continue`` and loop back through
            # the while-True. Cancel on the second sleep so we've observed
            # both branches (polling + re-enter) before bailing.
            if len(slept) >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(framework.asyncio, "sleep", _fake_sleep)

        await framework._plugin_invalidation_listener()
        # Both polls use the 10 s debug-path wait.
        assert slept == [10, 10]

    @pytest.mark.asyncio
    async def test_listener_subscribes_and_dispatches_one_message_then_cancels(self, monkeypatch):
        """The happy subscribe → listen → dispatch → cancel path runs to completion."""
        from mcpgateway.plugins import framework

        seen: list[dict] = []

        async def _fake_handle(msg):
            seen.append(msg)
            # End the listener via its ``except asyncio.CancelledError`` branch.
            raise asyncio.CancelledError()

        monkeypatch.setattr(framework, "_handle_invalidation_message", _fake_handle)

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()

        class _Listen:
            def __aiter__(self):
                return self

            async def __anext__(self):
                return {"type": "message", "data": "{}"}

        pubsub.listen = MagicMock(return_value=_Listen())

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        monkeypatch.setattr(framework, "_redis", AsyncMock(return_value=client))

        await framework._plugin_invalidation_listener()

        pubsub.subscribe.assert_awaited_once()
        assert len(seen) == 1
