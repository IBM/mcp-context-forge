# -*- coding: utf-8 -*-
"""Tests for CacheInvalidationSubscriber.

This module tests the cross-worker cache invalidation via Redis pubsub.
The CacheInvalidationSubscriber listens for invalidation messages published
by other workers and clears local in-memory caches accordingly.

Regression test for: REST /tools list endpoint returns stale visibility data
after tool update in multi-worker deployments.
"""

# Standard
import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.registry_cache import (
    CacheInvalidationSubscriber,
    get_cache_invalidation_subscriber,
)


@pytest.fixture
def cache_subscriber():
    """Create a fresh CacheInvalidationSubscriber instance."""
    subscriber = CacheInvalidationSubscriber()
    return subscriber


def create_mock_registry_cache(cache_data: dict) -> MagicMock:
    """Create a properly configured mock registry cache.

    Args:
        cache_data: Initial cache data dictionary

    Returns:
        MagicMock configured to behave like RegistryCache
    """
    mock = MagicMock()
    mock._cache = cache_data.copy()
    mock._lock = threading.Lock()
    # Configure _get_redis_key to return proper prefixes
    mock._get_redis_key = lambda key_type: f"{key_type}:"
    return mock


class TestCacheInvalidationSubscriber:
    """Tests for CacheInvalidationSubscriber."""

    def test_subscriber_initialization(self, cache_subscriber):
        """Test that subscriber initializes with correct defaults."""
        assert cache_subscriber._task is None
        assert cache_subscriber._stop_event is None
        assert cache_subscriber._pubsub is None
        assert cache_subscriber._channels == ["mcpgw:cache:invalidate", "mcpgw:auth:invalidate"]
        assert cache_subscriber._started is False

    @pytest.mark.asyncio
    async def test_process_registry_tools_invalidation(self, cache_subscriber):
        """Test processing of registry:tools invalidation message."""
        mock_registry_cache = create_mock_registry_cache(
            {
                "tools:hash1": {"data": "cached"},
                "prompts:hash2": {"data": "cached"},
            }
        )

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            await cache_subscriber._process_invalidation("registry:tools")

            # Tools cache should be cleared, prompts should remain
            assert "tools:hash1" not in mock_registry_cache._cache
            assert "prompts:hash2" in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_process_registry_prompts_invalidation(self, cache_subscriber):
        """Test processing of registry:prompts invalidation message."""
        mock_registry_cache = create_mock_registry_cache(
            {
                "tools:hash1": {"data": "cached"},
                "prompts:hash2": {"data": "cached"},
            }
        )

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            await cache_subscriber._process_invalidation("registry:prompts")

            # Prompts cache should be cleared, tools should remain
            assert "tools:hash1" in mock_registry_cache._cache
            assert "prompts:hash2" not in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_process_registry_resources_invalidation(self, cache_subscriber):
        """Test processing of registry:resources invalidation message."""
        mock_registry_cache = create_mock_registry_cache(
            {
                "resources:hash1": {"data": "cached"},
                "tools:hash2": {"data": "cached"},
            }
        )

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            await cache_subscriber._process_invalidation("registry:resources")

            assert "resources:hash1" not in mock_registry_cache._cache
            assert "tools:hash2" in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_process_tool_lookup_name_invalidation(self, cache_subscriber):
        """Test processing of tool_lookup:name invalidation message."""
        mock_tool_lookup = MagicMock()
        mock_tool_lookup._cache = {
            "tool-a": MagicMock(value={"status": "active"}),
            "tool-b": MagicMock(value={"status": "active"}),
        }
        mock_tool_lookup._lock = threading.Lock()

        with patch.dict("sys.modules", {"mcpgateway.cache.tool_lookup_cache": MagicMock(tool_lookup_cache=mock_tool_lookup)}):
            with patch("mcpgateway.cache.registry_cache.get_registry_cache"):
                await cache_subscriber._process_invalidation("tool_lookup:tool-a")

                # Specific tool should be cleared
                assert "tool-a" not in mock_tool_lookup._cache
                assert "tool-b" in mock_tool_lookup._cache

    @pytest.mark.asyncio
    async def test_process_tool_lookup_gateway_invalidation(self, cache_subscriber):
        """Test processing of tool_lookup:gateway:id invalidation message."""
        mock_tool_lookup = MagicMock()
        mock_tool_lookup._cache = {
            "tool-a": MagicMock(value={"status": "active", "tool": {"gateway_id": "gw-123"}}),
            "tool-b": MagicMock(value={"status": "active", "tool": {"gateway_id": "gw-456"}}),
        }
        mock_tool_lookup._lock = threading.Lock()

        with patch.dict("sys.modules", {"mcpgateway.cache.tool_lookup_cache": MagicMock(tool_lookup_cache=mock_tool_lookup)}):
            with patch("mcpgateway.cache.registry_cache.get_registry_cache"):
                await cache_subscriber._process_invalidation("tool_lookup:gateway:gw-123")

                # Tool with matching gateway should be cleared
                assert "tool-a" not in mock_tool_lookup._cache
                assert "tool-b" in mock_tool_lookup._cache

    @pytest.mark.asyncio
    async def test_process_admin_invalidation(self, cache_subscriber):
        """Test processing of admin:prefix invalidation message."""
        mock_admin_cache = MagicMock()
        mock_admin_cache._cache = {
            "admin:users:list": {"data": "cached"},
            "admin:teams:list": {"data": "cached"},
        }
        mock_admin_cache._lock = threading.Lock()
        mock_admin_cache._get_redis_key = lambda prefix: f"admin:{prefix}:"

        with patch.dict("sys.modules", {"mcpgateway.cache.admin_stats_cache": MagicMock(admin_stats_cache=mock_admin_cache)}):
            await cache_subscriber._process_invalidation("admin:users")

            # Admin users cache should be cleared
            assert "admin:users:list" not in mock_admin_cache._cache
            assert "admin:teams:list" in mock_admin_cache._cache

    @pytest.mark.asyncio
    async def test_process_unknown_message_format(self, cache_subscriber):
        """Test that unknown message formats are handled gracefully."""
        # Should not raise an exception
        await cache_subscriber._process_invalidation("unknown:format")
        await cache_subscriber._process_invalidation("")
        await cache_subscriber._process_invalidation("no-colon")

    @pytest.mark.asyncio
    async def test_start_without_redis(self, cache_subscriber):
        """Test that start handles missing Redis gracefully."""
        with patch("mcpgateway.utils.redis_client.get_redis_client", new=AsyncMock(return_value=None)):
            await cache_subscriber.start()
            # Should not crash, just log warning
            assert cache_subscriber._started is False

    @pytest.mark.asyncio
    async def test_start_when_already_started(self, cache_subscriber):
        cache_subscriber._started = True
        await cache_subscriber.start()
        assert cache_subscriber._started is True

    @pytest.mark.asyncio
    async def test_start_and_stop_with_pubsub(self, cache_subscriber, monkeypatch):
        class FakePubSub:
            def __init__(self):
                self.subscribed = False
                self.unsubscribed = False
                self.closed = False

            async def subscribe(self, *_channels):
                self.subscribed = True

            async def unsubscribe(self, *_channels):
                self.unsubscribed = True

            async def aclose(self):
                self.closed = True

        class FakeRedis:
            def pubsub(self):
                return FakePubSub()

        class DummyTask:
            def __init__(self):
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

            def __await__(self):
                async def _noop():
                    return None

                return _noop().__await__()

        def _create_task(coro):
            coro.close()
            return DummyTask()

        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedis()))
        monkeypatch.setattr(asyncio, "create_task", _create_task)

        await cache_subscriber.start()
        assert cache_subscriber._started is True

        await cache_subscriber.stop()
        assert cache_subscriber._started is False

    @pytest.mark.asyncio
    async def test_start_cleanup_on_exception(self, cache_subscriber, monkeypatch):
        class FakePubSub:
            async def subscribe(self, *_channels):
                raise RuntimeError("subscribe failed")

            async def aclose(self):
                raise AttributeError("no aclose")

            async def close(self):
                raise asyncio.TimeoutError()

        class FakeRedis:
            def pubsub(self):
                return FakePubSub()

        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedis()))
        await cache_subscriber.start()
        assert cache_subscriber._started is False
        assert cache_subscriber._pubsub is None

    @pytest.mark.asyncio
    async def test_start_cleanup_on_exception_handles_cleanup_error(self, cache_subscriber, monkeypatch):
        class FakePubSub:
            async def subscribe(self, *_channels):
                raise RuntimeError("subscribe failed")

            async def aclose(self):
                raise RuntimeError("aclose boom")

        class FakeRedis:
            def pubsub(self):
                return FakePubSub()

        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedis()))

        await cache_subscriber.start()
        assert cache_subscriber._started is False
        assert cache_subscriber._pubsub is None

    @pytest.mark.asyncio
    async def test_listen_loop_processes_message(self, cache_subscriber, monkeypatch):
        stop_event = asyncio.Event()

        class FakePubSub:
            def __init__(self):
                self.called = False

            async def get_message(self, **_kwargs):
                if not self.called:
                    self.called = True
                    stop_event.set()
                    return {"type": "message", "data": b"registry:tools"}
                return None

        cache_subscriber._pubsub = FakePubSub()
        cache_subscriber._stop_event = stop_event
        cache_subscriber._started = True

        monkeypatch.setattr(cache_subscriber, "_process_invalidation", AsyncMock())

        await cache_subscriber._listen_loop()
        assert cache_subscriber._process_invalidation.await_count == 1

    @pytest.mark.asyncio
    async def test_listen_loop_forwards_channel_to_process_invalidation(self, cache_subscriber, monkeypatch):
        """Regression: _listen_loop must extract and forward the pubsub channel.

        Without this, auth invalidation messages would arrive with channel=""
        and be rejected by the channel-origin guard, silently reintroducing
        the cross-replica auth cache bug.
        """
        stop_event = asyncio.Event()

        class FakePubSub:
            def __init__(self):
                self.called = False

            async def get_message(self, **_kwargs):
                if not self.called:
                    self.called = True
                    stop_event.set()
                    return {"type": "message", "data": b"user:alice@test.com", "channel": b"mcpgw:auth:invalidate"}
                return None

        cache_subscriber._pubsub = FakePubSub()
        cache_subscriber._stop_event = stop_event
        cache_subscriber._started = True

        monkeypatch.setattr(cache_subscriber, "_process_invalidation", AsyncMock())

        await cache_subscriber._listen_loop()
        cache_subscriber._process_invalidation.assert_awaited_once_with("user:alice@test.com", channel="mcpgw:auth:invalidate")

    @pytest.mark.asyncio
    async def test_listen_loop_timeout(self, cache_subscriber):
        stop_event = asyncio.Event()

        class TimeoutPubSub:
            def __init__(self):
                self.called = False

            async def get_message(self, **_kwargs):
                if not self.called:
                    self.called = True
                    stop_event.set()
                    raise asyncio.TimeoutError()
                return None

        cache_subscriber._pubsub = TimeoutPubSub()
        cache_subscriber._stop_event = stop_event
        cache_subscriber._started = True

        await cache_subscriber._listen_loop()

    @pytest.mark.asyncio
    async def test_listen_loop_exits_when_pubsub_missing(self, cache_subscriber):
        cache_subscriber._pubsub = None
        cache_subscriber._stop_event = asyncio.Event()
        cache_subscriber._started = True

        await cache_subscriber._listen_loop()

    @pytest.mark.asyncio
    async def test_listen_loop_skips_non_message_and_empty_data(self, cache_subscriber, monkeypatch):
        stop_event = asyncio.Event()

        class FakePubSub:
            def __init__(self):
                self.calls = 0

            async def get_message(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {"type": "subscribe", "data": "ignored"}
                stop_event.set()
                return {"type": "message", "data": ""}  # not bytes + falsy payload

        cache_subscriber._pubsub = FakePubSub()
        cache_subscriber._stop_event = stop_event
        cache_subscriber._started = True

        monkeypatch.setattr(cache_subscriber, "_process_invalidation", AsyncMock())

        await cache_subscriber._listen_loop()
        cache_subscriber._process_invalidation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listen_loop_handles_message_error_and_sleeps(self, cache_subscriber, monkeypatch):
        stop_event = asyncio.Event()

        class ErrorPubSub:
            async def get_message(self, **_kwargs):
                stop_event.set()
                raise RuntimeError("boom")

        cache_subscriber._pubsub = ErrorPubSub()
        cache_subscriber._stop_event = stop_event
        cache_subscriber._started = True

        sleep = AsyncMock()
        monkeypatch.setattr(asyncio, "sleep", sleep)

        await cache_subscriber._listen_loop()
        sleep.assert_awaited()

    @pytest.mark.asyncio
    async def test_listen_loop_cancelled_error_is_reraised(self, cache_subscriber):
        stop_event = asyncio.Event()

        class CancelPubSub:
            async def get_message(self, **_kwargs):
                raise asyncio.CancelledError()

        cache_subscriber._pubsub = CancelPubSub()
        cache_subscriber._stop_event = stop_event
        cache_subscriber._started = True

        with pytest.raises(asyncio.CancelledError):
            await cache_subscriber._listen_loop()

    @pytest.mark.asyncio
    async def test_process_invalidation_error_path(self, cache_subscriber):
        with patch("mcpgateway.cache.registry_cache.get_registry_cache", side_effect=RuntimeError("boom")):
            await cache_subscriber._process_invalidation("registry:tools")

    @pytest.mark.asyncio
    async def test_stop_without_start(self, cache_subscriber):
        """Test that stop is safe to call without start."""
        await cache_subscriber.stop()
        # Should not raise an exception
        assert cache_subscriber._started is False

    @pytest.mark.asyncio
    async def test_stop_task_wait_for_timeout_is_swallowed(self, cache_subscriber, monkeypatch):
        cache_subscriber._started = True
        cache_subscriber._stop_event = asyncio.Event()

        class DummyTask:
            def __init__(self):
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

        cache_subscriber._task = DummyTask()
        cache_subscriber._pubsub = None

        async def fake_wait_for(_awaitable, timeout=None):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

        await cache_subscriber.stop()
        assert cache_subscriber._task is None

    @pytest.mark.asyncio
    async def test_stop_pubsub_unsubscribe_timeout_and_close_timeout(self, cache_subscriber):
        cache_subscriber._started = True
        cache_subscriber._stop_event = asyncio.Event()
        cache_subscriber._task = None

        class FakePubSub:
            async def unsubscribe(self, *_channels):
                raise asyncio.TimeoutError()

            async def close(self):
                raise asyncio.TimeoutError()

        cache_subscriber._pubsub = FakePubSub()

        await cache_subscriber.stop()
        assert cache_subscriber._pubsub is None

    @pytest.mark.asyncio
    async def test_stop_pubsub_unsubscribe_exception_and_close_exception(self, cache_subscriber):
        cache_subscriber._started = True
        cache_subscriber._stop_event = asyncio.Event()
        cache_subscriber._task = None

        class FakePubSub:
            async def unsubscribe(self, *_channels):
                raise RuntimeError("unsubscribe boom")

            async def close(self):
                raise RuntimeError("close boom")

        cache_subscriber._pubsub = FakePubSub()

        await cache_subscriber.stop()
        assert cache_subscriber._pubsub is None

    def test_singleton_getter(self):
        """Test that get_cache_invalidation_subscriber returns singleton."""
        sub1 = get_cache_invalidation_subscriber()
        sub2 = get_cache_invalidation_subscriber()
        assert sub1 is sub2


class TestCrossWorkerCacheInvalidation:
    """Integration-style tests for cross-worker cache invalidation scenario.

    These tests verify the end-to-end behavior that when a tool's visibility
    is updated, the cache invalidation message is properly processed and
    local caches are cleared.
    """

    @pytest.mark.asyncio
    async def test_tool_visibility_update_clears_registry_cache(self):
        """Test that tool visibility update triggers registry cache invalidation.

        This is the main regression test for the bug where REST /tools list
        returned stale visibility data after tool update.
        """
        subscriber = CacheInvalidationSubscriber()

        mock_registry_cache = create_mock_registry_cache(
            {
                "tools:default": [{"name": "my-tool", "visibility": "public"}],
                "tools:filtered": [{"name": "my-tool", "visibility": "public"}],
            }
        )

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            # Simulate receiving invalidation message (as would happen from another worker)
            await subscriber._process_invalidation("registry:tools")

            # All tools caches should be cleared
            assert "tools:default" not in mock_registry_cache._cache
            assert "tools:filtered" not in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_multiple_invalidation_messages(self):
        """Test handling of multiple rapid invalidation messages."""
        subscriber = CacheInvalidationSubscriber()

        mock_registry_cache = create_mock_registry_cache(
            {
                "tools:h1": {"data": "1"},
                "tools:h2": {"data": "2"},
                "prompts:h1": {"data": "1"},
                "resources:h1": {"data": "1"},
            }
        )

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            # Rapid-fire invalidations
            await asyncio.gather(
                subscriber._process_invalidation("registry:tools"),
                subscriber._process_invalidation("registry:prompts"),
                subscriber._process_invalidation("registry:resources"),
            )

            # All should be cleared
            assert len(mock_registry_cache._cache) == 0

    @pytest.mark.asyncio
    async def test_invalidation_message_parsing(self):
        """Test that different message formats are parsed correctly."""
        subscriber = CacheInvalidationSubscriber()

        mock_registry_cache = create_mock_registry_cache({})

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            # These should not raise exceptions
            await subscriber._process_invalidation("registry:tools")
            await subscriber._process_invalidation("registry:prompts")
            await subscriber._process_invalidation("registry:resources")
            await subscriber._process_invalidation("registry:agents")
            await subscriber._process_invalidation("tool_lookup:my-tool")
            await subscriber._process_invalidation("tool_lookup:gateway:gw-123")
            await subscriber._process_invalidation("admin:users")
            await subscriber._process_invalidation("admin:teams")
            # Unknown formats should be handled gracefully
            await subscriber._process_invalidation("unknown:type")
            await subscriber._process_invalidation("malformed")
            await subscriber._process_invalidation("")


def create_mock_auth_cache(
    user_cache=None,
    team_cache=None,
    context_cache=None,
    role_cache=None,
    teams_list_cache=None,
    revocation_cache=None,
    revoked_jtis=None,
):
    """Create a properly configured mock auth cache.

    Returns:
        MagicMock configured to behave like AuthCache
    """
    mock = MagicMock()
    mock._user_cache = user_cache if user_cache is not None else {}
    mock._team_cache = team_cache if team_cache is not None else {}
    mock._context_cache = context_cache if context_cache is not None else {}
    mock._role_cache = role_cache if role_cache is not None else {}
    mock._teams_list_cache = teams_list_cache if teams_list_cache is not None else {}
    mock._revocation_cache = revocation_cache if revocation_cache is not None else {}
    mock._revoked_jtis = revoked_jtis if revoked_jtis is not None else set()
    mock._lock = threading.Lock()
    return mock


class TestAuthCacheInvalidationSubscriber:
    """Tests for auth cache invalidation via CacheInvalidationSubscriber.

    Regression test for: auth_cache published invalidation messages to
    mcpgw:auth:invalidate but CacheInvalidationSubscriber only listened
    on mcpgw:cache:invalidate, so other replicas never cleared their
    in-memory auth caches.
    """

    @pytest.mark.asyncio
    async def test_subscriber_subscribes_to_both_channels(self):
        """Test that subscriber subscribes to both cache and auth channels."""
        subscriber = CacheInvalidationSubscriber()
        assert "mcpgw:cache:invalidate" in subscriber._channels
        assert "mcpgw:auth:invalidate" in subscriber._channels

    @pytest.mark.asyncio
    async def test_start_subscribes_to_both_channels(self, monkeypatch):
        """Test that start() subscribes the pubsub to both channels."""
        subscribed_channels = []

        class FakePubSub:
            async def subscribe(self, *channels):
                subscribed_channels.extend(channels)

        class FakeRedis:
            def pubsub(self):
                return FakePubSub()

        class DummyTask:
            def cancel(self):
                pass

            def __await__(self):
                async def _noop():
                    return None

                return _noop().__await__()

        def _create_task(coro):
            coro.close()
            return DummyTask()

        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=FakeRedis()))
        monkeypatch.setattr(asyncio, "create_task", _create_task)

        subscriber = CacheInvalidationSubscriber()
        await subscriber.start()
        assert "mcpgw:cache:invalidate" in subscribed_channels
        assert "mcpgw:auth:invalidate" in subscribed_channels
        await subscriber.stop()

    @pytest.mark.asyncio
    async def test_process_user_invalidation(self):
        """Test processing of user:{email} auth invalidation message."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            user_cache={"alice@test.com": "user-data", "bob@test.com": "user-data"},
            context_cache={"alice@test.com:jti1": "ctx-data", "bob@test.com:jti2": "ctx-data"},
            team_cache={"alice@test.com:team1": "team-data", "bob@test.com:team2": "team-data"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("user:alice@test.com", channel="mcpgw:auth:invalidate")

        assert "alice@test.com" not in mock_auth._user_cache
        assert "bob@test.com" in mock_auth._user_cache
        assert "alice@test.com:jti1" not in mock_auth._context_cache
        assert "bob@test.com:jti2" in mock_auth._context_cache
        assert "alice@test.com:team1" not in mock_auth._team_cache
        assert "bob@test.com:team2" in mock_auth._team_cache

    @pytest.mark.asyncio
    async def test_process_revoke_invalidation(self):
        """Test processing of revoke:{jti} auth invalidation message."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            revocation_cache={"jti-abc123": "cached", "jti-other": "cached"},
            context_cache={"user@test.com:jti-abc123": "ctx-data", "user@test.com:jti-other": "ctx-data"},
            revoked_jtis=set(),
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("revoke:jti-abc123", channel="mcpgw:auth:invalidate")

        assert "jti-abc123" in mock_auth._revoked_jtis
        assert "jti-abc123" not in mock_auth._revocation_cache
        assert "jti-other" in mock_auth._revocation_cache
        assert "user@test.com:jti-abc123" not in mock_auth._context_cache
        assert "user@test.com:jti-other" in mock_auth._context_cache

    @pytest.mark.asyncio
    async def test_process_team_invalidation(self):
        """Test processing of team:{email} auth invalidation message."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            team_cache={"alice@test.com": "team-data", "bob@test.com": "team-data"},
            context_cache={"alice@test.com:jti1": "ctx-data", "bob@test.com:jti2": "ctx-data"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("team:alice@test.com", channel="mcpgw:auth:invalidate")

        assert "alice@test.com" not in mock_auth._team_cache
        assert "bob@test.com" in mock_auth._team_cache
        assert "alice@test.com:jti1" not in mock_auth._context_cache
        assert "bob@test.com:jti2" in mock_auth._context_cache

    @pytest.mark.asyncio
    async def test_process_role_invalidation(self):
        """Test processing of role:{email}:{team_id} auth invalidation message."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            role_cache={
                "alice@test.com:team-123": "developer",
                "alice@test.com:team-456": "viewer",
                "bob@test.com:team-123": "admin",
            },
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("role:alice@test.com:team-123", channel="mcpgw:auth:invalidate")

        assert "alice@test.com:team-123" not in mock_auth._role_cache
        assert "alice@test.com:team-456" in mock_auth._role_cache
        assert "bob@test.com:team-123" in mock_auth._role_cache

    @pytest.mark.asyncio
    async def test_process_team_roles_invalidation(self):
        """Test processing of team_roles:{team_id} auth invalidation message."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            role_cache={
                "alice@test.com:team-123": "developer",
                "bob@test.com:team-123": "admin",
                "carol@test.com:team-456": "viewer",
            },
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("team_roles:team-123", channel="mcpgw:auth:invalidate")

        assert "alice@test.com:team-123" not in mock_auth._role_cache
        assert "bob@test.com:team-123" not in mock_auth._role_cache
        assert "carol@test.com:team-456" in mock_auth._role_cache

    @pytest.mark.asyncio
    async def test_process_teams_list_invalidation(self):
        """Test processing of teams:{email} auth invalidation message."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            teams_list_cache={
                "alice@test.com:True": ["team-1", "team-2"],
                "alice@test.com:False": ["team-1"],
                "bob@test.com:True": ["team-3"],
            },
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("teams:alice@test.com", channel="mcpgw:auth:invalidate")

        assert "alice@test.com:True" not in mock_auth._teams_list_cache
        assert "alice@test.com:False" not in mock_auth._teams_list_cache
        assert "bob@test.com:True" in mock_auth._teams_list_cache

    @pytest.mark.asyncio
    async def test_process_membership_invalidation(self):
        """Test processing of membership:{email} auth invalidation message."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            team_cache={
                "alice@test.com:team-1,team-2": True,
                "alice@test.com:team-3": False,
                "bob@test.com:team-1": True,
            },
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("membership:alice@test.com", channel="mcpgw:auth:invalidate")

        assert "alice@test.com:team-1,team-2" not in mock_auth._team_cache
        assert "alice@test.com:team-3" not in mock_auth._team_cache
        assert "bob@test.com:team-1" in mock_auth._team_cache

    @pytest.mark.asyncio
    async def test_auth_invalidation_message_parsing(self):
        """Test that all auth message formats are parsed correctly without errors."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache()

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            # All auth message types should not raise exceptions
            await subscriber._process_invalidation("user:test@example.com", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("revoke:jti-12345678", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("team:test@example.com", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("role:test@example.com:team-123", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("team_roles:team-123", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("teams:test@example.com", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("membership:test@example.com", channel="mcpgw:auth:invalidate")

    @pytest.mark.asyncio
    async def test_cross_replica_auth_invalidation_end_to_end(self):
        """End-to-end test: auth invalidation clears local cache on other replica.

        This is the main regression test for the cross-replica auth cache
        invalidation gap where auth_cache published to mcpgw:auth:invalidate
        but CacheInvalidationSubscriber only listened on mcpgw:cache:invalidate.
        """
        subscriber = CacheInvalidationSubscriber()

        # Simulate a replica with warm auth caches
        mock_auth = create_mock_auth_cache(
            user_cache={"admin@company.com": "user-data"},
            context_cache={"admin@company.com:jti-xyz": "ctx-data"},
            team_cache={"admin@company.com:team-a,team-b": True},
            role_cache={"admin@company.com:team-a": "platform_admin"},
            teams_list_cache={"admin@company.com:True": ["team-a", "team-b"]},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            # Simulate receiving invalidation from another replica
            # (e.g., after user role change on replica 1, replica 2 gets this)
            await subscriber._process_invalidation("user:admin@company.com", channel="mcpgw:auth:invalidate")

        # All caches for this user should be cleared
        assert "admin@company.com" not in mock_auth._user_cache
        assert "admin@company.com:jti-xyz" not in mock_auth._context_cache
        assert "admin@company.com:team-a,team-b" not in mock_auth._team_cache

    @pytest.mark.asyncio
    async def test_revoke_skips_add_when_revoked_jtis_at_cap(self, monkeypatch):
        """Test that revoke handler respects _MAX_REVOKED_JTIS cap."""
        cap = 5
        monkeypatch.setattr("mcpgateway.cache.registry_cache._MAX_REVOKED_JTIS", cap)

        subscriber = CacheInvalidationSubscriber()
        # Pre-fill _revoked_jtis to the cap
        existing_jtis = {f"old-jti-{i}" for i in range(cap)}
        mock_auth = create_mock_auth_cache(
            revoked_jtis=existing_jtis,
            revocation_cache={"new-jti": "cached"},
            context_cache={"user@test.com:new-jti": "ctx-data"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("revoke:new-jti", channel="mcpgw:auth:invalidate")

        # JTI should NOT be added to the set (cap reached)
        assert "new-jti" not in mock_auth._revoked_jtis
        assert len(mock_auth._revoked_jtis) == cap
        # But cache eviction should still happen
        assert "new-jti" not in mock_auth._revocation_cache
        assert "user@test.com:new-jti" not in mock_auth._context_cache

    @pytest.mark.asyncio
    async def test_revoke_adds_jti_when_below_cap(self):
        """Test that revoke handler adds JTI when below _MAX_REVOKED_JTIS cap."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            revoked_jtis={"existing-jti"},
            revocation_cache={"new-jti": "cached"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("revoke:new-jti", channel="mcpgw:auth:invalidate")

        assert "new-jti" in mock_auth._revoked_jtis

    @pytest.mark.asyncio
    async def test_teams_message_dispatches_to_correct_handler(self):
        """Verify 'teams:' is dispatched to teams handler, not 'team:' handler."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            team_cache={"alice@test.com": "should-remain"},
            teams_list_cache={"alice@test.com:True": ["team-1"]},
            context_cache={"alice@test.com:jti1": "should-remain"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("teams:alice@test.com", channel="mcpgw:auth:invalidate")

        # teams: should only clear _teams_list_cache, not _team_cache or _context_cache
        assert "alice@test.com:True" not in mock_auth._teams_list_cache
        assert "alice@test.com" in mock_auth._team_cache
        assert "alice@test.com:jti1" in mock_auth._context_cache

    @pytest.mark.asyncio
    async def test_team_roles_message_dispatches_to_correct_handler(self):
        """Verify 'team_roles:' is dispatched to team_roles handler, not 'team:' handler."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            team_cache={"alice@test.com": "should-remain"},
            role_cache={"alice@test.com:team-99": "developer", "bob@test.com:team-99": "admin"},
            context_cache={"alice@test.com:jti1": "should-remain"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("team_roles:team-99", channel="mcpgw:auth:invalidate")

        # team_roles: should only clear _role_cache, not _team_cache or _context_cache
        assert "alice@test.com:team-99" not in mock_auth._role_cache
        assert "bob@test.com:team-99" not in mock_auth._role_cache
        assert "alice@test.com" in mock_auth._team_cache
        assert "alice@test.com:jti1" in mock_auth._context_cache

    @pytest.mark.asyncio
    async def test_empty_identifier_after_prefix(self):
        """Edge case: messages with empty identifier after prefix don't crash."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache()

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("user:", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("revoke:", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("team:", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("role:", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("team_roles:", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("teams:", channel="mcpgw:auth:invalidate")
            await subscriber._process_invalidation("membership:", channel="mcpgw:auth:invalidate")

    @pytest.mark.asyncio
    async def test_identifier_containing_colons(self):
        """Edge case: identifiers with extra colons are handled correctly."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            role_cache={"user@co:with:extra": "developer", "clean@co:team-1": "viewer"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            # role: strips only the "role:" prefix; remainder is the full cache key
            await subscriber._process_invalidation("role:user@co:with:extra", channel="mcpgw:auth:invalidate")

        assert "user@co:with:extra" not in mock_auth._role_cache
        assert "clean@co:team-1" in mock_auth._role_cache

    @pytest.mark.asyncio
    async def test_membership_identifier_with_colon_in_email(self):
        """Edge case: email-like identifiers with unusual chars."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            team_cache={"odd:user@test.com:team-1": True, "normal@test.com:team-2": True},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("membership:odd:user@test.com", channel="mcpgw:auth:invalidate")

        # Should evict keys starting with "odd:user@test.com:"
        assert "odd:user@test.com:team-1" not in mock_auth._team_cache
        assert "normal@test.com:team-2" in mock_auth._team_cache

    @pytest.mark.asyncio
    async def test_auth_message_rejected_on_wrong_channel(self):
        """Deny-path: auth messages on mcpgw:cache:invalidate are ignored."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            user_cache={"alice@test.com": "user-data"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("user:alice@test.com", channel="mcpgw:cache:invalidate")

        # Cache must NOT have been evicted
        assert "alice@test.com" in mock_auth._user_cache

    @pytest.mark.asyncio
    async def test_auth_message_accepted_on_correct_channel(self):
        """Auth messages on mcpgw:auth:invalidate are processed normally."""
        subscriber = CacheInvalidationSubscriber()
        mock_auth = create_mock_auth_cache(
            user_cache={"alice@test.com": "user-data"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._process_invalidation("user:alice@test.com", channel="mcpgw:auth:invalidate")

        assert "alice@test.com" not in mock_auth._user_cache

    @pytest.mark.asyncio
    async def test_registry_message_unaffected_by_channel_guard(self):
        """Registry messages on mcpgw:cache:invalidate still work as before."""
        subscriber = CacheInvalidationSubscriber()
        mock_registry_cache = create_mock_registry_cache({"tools:hash1": {"data": "cached"}})

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            await subscriber._process_invalidation("registry:tools", channel="mcpgw:cache:invalidate")

        assert "tools:hash1" not in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_listen_loop_auth_message_evicts_cache_end_to_end(self):
        """End-to-end: auth pubsub message flows through _listen_loop and evicts auth cache.

        This tests the full path: _listen_loop extracts channel from the Redis
        pubsub message, forwards it to _process_invalidation, which dispatches
        to _process_auth_invalidation, which evicts the auth cache entry.
        A regression that drops channel forwarding would cause this test to fail.
        """
        subscriber = CacheInvalidationSubscriber()
        stop_event = asyncio.Event()

        class FakePubSub:
            def __init__(self):
                self.called = False

            async def get_message(self, **_kwargs):
                if not self.called:
                    self.called = True
                    stop_event.set()
                    return {"type": "message", "data": b"user:alice@test.com", "channel": b"mcpgw:auth:invalidate"}
                return None

        subscriber._pubsub = FakePubSub()
        subscriber._stop_event = stop_event
        subscriber._started = True

        mock_auth = create_mock_auth_cache(
            user_cache={"alice@test.com": "user-data", "bob@test.com": "user-data"},
            context_cache={"alice@test.com:jti1": "ctx", "bob@test.com:jti2": "ctx"},
            team_cache={"alice@test.com:team1": "team", "bob@test.com:team2": "team"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._listen_loop()

        # alice's caches cleared, bob's untouched
        assert "alice@test.com" not in mock_auth._user_cache
        assert "bob@test.com" in mock_auth._user_cache
        assert "alice@test.com:jti1" not in mock_auth._context_cache
        assert "bob@test.com:jti2" in mock_auth._context_cache

    @pytest.mark.asyncio
    async def test_listen_loop_auth_message_rejected_on_wrong_channel_end_to_end(self):
        """End-to-end deny-path: auth message on cache channel is ignored by _listen_loop."""
        subscriber = CacheInvalidationSubscriber()
        stop_event = asyncio.Event()

        class FakePubSub:
            def __init__(self):
                self.called = False

            async def get_message(self, **_kwargs):
                if not self.called:
                    self.called = True
                    stop_event.set()
                    return {"type": "message", "data": b"user:alice@test.com", "channel": b"mcpgw:cache:invalidate"}
                return None

        subscriber._pubsub = FakePubSub()
        subscriber._stop_event = stop_event
        subscriber._started = True

        mock_auth = create_mock_auth_cache(
            user_cache={"alice@test.com": "user-data"},
        )

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth):
            await subscriber._listen_loop()

        # Cache must NOT have been evicted (wrong channel)
        assert "alice@test.com" in mock_auth._user_cache
