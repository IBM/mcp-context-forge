# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/services/test_event_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

Description:

Comprehensive test suite for EventService with maximum code coverage.

"""

import asyncio
import importlib
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
import orjson
import pytest
import sys


class TestEventService:
    """Test suite for EventService with comprehensive coverage."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings configuration."""
        with patch("mcpgateway.services.event_service.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.cache_type = "redis"
            yield mock_settings

    @pytest.fixture
    def mock_redis_available(self):
        """Mock Redis availability."""
        with patch("mcpgateway.services.event_service.REDIS_AVAILABLE", True):
            yield

    @pytest.fixture
    def mock_redis_unavailable(self):
        """Mock Redis unavailability."""
        with patch("mcpgateway.services.event_service.REDIS_AVAILABLE", False):
            yield

    # Test __init__ method

    @pytest.mark.asyncio
    async def test_init_with_redis_success(self, mock_settings, mock_redis_available):
        """Test initialization with successful Redis connection."""
        mock_redis_client = AsyncMock()

        async def mock_get_redis_client():
            return mock_redis_client

        with patch("mcpgateway.services.event_service.get_redis_client", mock_get_redis_client):
            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")
            await service.initialize()

            assert service.channel_name == "test:channel"
            assert service.redis_url == "redis://localhost:6379"
            assert service._redis_client is not None
            assert service._event_subscribers == []

    @pytest.mark.asyncio
    async def test_init_with_redis_connection_failure(self, mock_settings, mock_redis_available):
        """Test initialization when Redis connection fails."""
        async def mock_get_redis_client():
            raise Exception("Connection failed")

        with patch("mcpgateway.services.event_service.get_redis_client", mock_get_redis_client):
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")
                await service.initialize()

                assert service._redis_client is None
                mock_logger.warning.assert_called_once()
                assert "Failed to initialize Redis" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_init_with_redis_ping_failure(self, mock_settings, mock_redis_available):
        """Test initialization when shared client returns None (unavailable)."""
        async def mock_get_redis_client():
            return None

        with patch("mcpgateway.services.event_service.get_redis_client", mock_get_redis_client):
            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")
            await service.initialize()

            assert service._redis_client is None

    @pytest.mark.asyncio
    async def test_init_without_redis_available(self, mock_settings, mock_redis_unavailable):
        """Test initialization when Redis is not available."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        assert service._redis_client is None
        assert service.redis_url == "redis://localhost:6379"

    @pytest.mark.asyncio
    async def test_init_with_non_redis_cache_type(self, mock_redis_available):
        """Test initialization when cache_type is not redis."""
        with patch("mcpgateway.services.event_service.settings") as mock_settings:
            mock_settings.cache_type = "memory"
            mock_settings.redis_url = "redis://localhost:6379"

            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")

            assert service.redis_url is None
            assert service._redis_client is None

    # Test publish_event method

    @pytest.mark.asyncio
    async def test_publish_event_with_redis_success(self, mock_settings, mock_redis_available):
        """Test successful event publishing via Redis."""
        mock_redis_client = AsyncMock()
        mock_redis_client.publish = AsyncMock()

        async def mock_get_redis_client():
            return mock_redis_client

        with patch("mcpgateway.services.event_service.get_redis_client", mock_get_redis_client):
            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")
            await service.initialize()
            event_data = {"event": "test_event", "data": "test_data"}

            await service.publish_event(event_data)

            mock_redis_client.publish.assert_called_once()
            call_args = mock_redis_client.publish.call_args[0]
            assert call_args[0] == "test:channel"
            assert orjson.loads(call_args[1]) == event_data

    @pytest.mark.asyncio
    async def test_publish_event_with_redis_failure_fallback_to_local(
        self, mock_settings, mock_redis_available
    ):
        """Test event publishing falls back to local queues when Redis fails."""
        mock_redis_client = AsyncMock()
        mock_redis_client.publish = AsyncMock(side_effect=Exception("Redis publish failed"))

        async def mock_get_redis_client():
            return mock_redis_client

        with patch("mcpgateway.services.event_service.get_redis_client", mock_get_redis_client):
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")
                await service.initialize()

                queue1 = asyncio.Queue()
                queue2 = asyncio.Queue()
                service._event_subscribers.append(queue1)
                service._event_subscribers.append(queue2)

                event_data = {"event": "test_event", "data": "test_data"}

                await service.publish_event(event_data)

                assert await queue1.get() == event_data
                assert await queue2.get() == event_data
                mock_logger.error.assert_called_once()
                assert "Failed to publish event" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_publish_event_local_mode_only(self, mock_settings, mock_redis_unavailable):
        """Test event publishing in local mode (no Redis)."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()
        service._event_subscribers.append(queue1)
        service._event_subscribers.append(queue2)

        event_data = {"event": "test_event", "data": "test_data"}
        await service.publish_event(event_data)

        assert await queue1.get() == event_data
        assert await queue2.get() == event_data

    @pytest.mark.asyncio
    async def test_publish_event_with_empty_subscribers(self, mock_settings, mock_redis_unavailable):
        """Test publishing when there are no subscribers."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")
        event_data = {"event": "test_event"}
        await service.publish_event(event_data)

    # Test subscribe_events method - Redis tests

    @pytest.mark.skip
    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_with_redis(self, mock_settings, mock_redis_available):
        """Test event subscription via Redis PubSub."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True
            mock_redis_module.from_url.return_value = mock_redis_client

            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")

            mock_aioredis_module = MagicMock()
            mock_async_client = AsyncMock()
            mock_pubsub = AsyncMock()

            async def mock_listen():
                yield {"type": "subscribe", "data": None}
                yield {"type": "message", "data": json.dumps({"event": "test1"})}
                yield {"type": "message", "data": json.dumps({"event": "test2"})}
                return

            mock_pubsub.listen.return_value = mock_listen()
            mock_pubsub.subscribe = AsyncMock()
            mock_pubsub.unsubscribe = AsyncMock()
            mock_async_client.pubsub.return_value = mock_pubsub
            mock_async_client.aclose = AsyncMock()
            mock_aioredis_module.from_url.return_value = mock_async_client

            sys.modules["redis.asyncio"] = mock_aioredis_module

            try:
                events = []
                async for event in service.subscribe_events():
                    events.append(event)

                assert len(events) == 2
                assert events[0] == {"event": "test1"}
                assert events[1] == {"event": "test2"}
                mock_pubsub.subscribe.assert_called_once_with("test:channel")
                mock_pubsub.unsubscribe.assert_called_once_with("test:channel")
                mock_async_client.aclose.assert_called_once()
            finally:
                if "redis.asyncio" in sys.modules:
                    del sys.modules["redis.asyncio"]

    @pytest.mark.skip
    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_with_redis_cancellation(
        self, mock_settings, mock_redis_available
    ):
        """Test event subscription cancellation with Redis."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                mock_redis_client = MagicMock()
                mock_redis_client.ping.return_value = True
                mock_redis_module.from_url.return_value = mock_redis_client

                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")

                mock_aioredis_module = MagicMock()
                mock_async_client = AsyncMock()
                mock_pubsub = AsyncMock()

                async def mock_listen():
                    yield {"type": "message", "data": json.dumps({"event": "test"})}
                    while True:
                        await asyncio.sleep(1)

                mock_pubsub.listen.return_value = mock_listen()
                mock_pubsub.subscribe = AsyncMock()
                mock_pubsub.unsubscribe = AsyncMock()
                mock_async_client.pubsub.return_value = mock_pubsub
                mock_async_client.aclose = AsyncMock()
                mock_aioredis_module.from_url.return_value = mock_async_client

                sys.modules["redis.asyncio"] = mock_aioredis_module

                try:
                    async def consume():
                        async for event in service.subscribe_events():
                            pass

                    task = asyncio.create_task(consume())
                    await asyncio.sleep(0.3)
                    task.cancel()

                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                    await asyncio.sleep(0.1)

                    mock_pubsub.unsubscribe.assert_called_once_with("test:channel")
                    mock_async_client.aclose.assert_called_once()
                    mock_logger.error.assert_called()
                    assert "Client disconnected" in str(mock_logger.error.call_args)
                finally:
                    if "redis.asyncio" in sys.modules:
                        del sys.modules["redis.asyncio"]

    @pytest.mark.skip
    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_with_redis_exception(self, mock_settings, mock_redis_available):
        """Test event subscription with Redis exception."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                mock_redis_client = MagicMock()
                mock_redis_client.ping.return_value = True
                mock_redis_module.from_url.return_value = mock_redis_client

                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")

                mock_aioredis_module = MagicMock()
                mock_async_client = AsyncMock()
                mock_pubsub = AsyncMock()

                async def mock_listen():
                    yield {"type": "message", "data": json.dumps({"event": "test"})}
                    raise Exception("Redis error")

                mock_pubsub.listen.return_value = mock_listen()
                mock_pubsub.subscribe = AsyncMock()
                mock_pubsub.unsubscribe = AsyncMock()
                mock_async_client.pubsub.return_value = mock_pubsub
                mock_async_client.aclose = AsyncMock()
                mock_aioredis_module.from_url.return_value = mock_async_client

                sys.modules["redis.asyncio"] = mock_aioredis_module

                try:
                    with pytest.raises(Exception) as exc_info:
                        async for _ in service.subscribe_events():
                            pass

                    assert str(exc_info.value) == "Redis error"
                    mock_logger.error.assert_called()
                    mock_pubsub.unsubscribe.assert_called_once()
                    mock_async_client.aclose.assert_called_once()
                finally:
                    if "redis.asyncio" in sys.modules:
                        del sys.modules["redis.asyncio"]

    @pytest.mark.skip
    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_with_redis_cleanup_error(
        self, mock_settings, mock_redis_available
    ):
        """Test event subscription with Redis cleanup error."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                mock_redis_client = MagicMock()
                mock_redis_client.ping.return_value = True
                mock_redis_module.from_url.return_value = mock_redis_client

                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")

                mock_aioredis_module = MagicMock()
                mock_async_client = AsyncMock()
                mock_pubsub = AsyncMock()

                async def mock_listen():
                    raise Exception("Connection error")

                mock_pubsub.listen.return_value = mock_listen()
                mock_pubsub.subscribe = AsyncMock()
                mock_pubsub.unsubscribe = AsyncMock(side_effect=Exception("Cleanup error"))
                mock_async_client.pubsub.return_value = mock_pubsub
                mock_async_client.aclose = AsyncMock()
                mock_aioredis_module.from_url.return_value = mock_async_client

                sys.modules["redis.asyncio"] = mock_aioredis_module

                try:
                    with pytest.raises(Exception) as exc_info:
                        async for _ in service.subscribe_events():
                            pass

                    assert str(exc_info.value) == "Connection error"
                    warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
                    assert any(
                        "Error closing Redis subscription" in call_str for call_str in warning_calls
                    )
                finally:
                    if "redis.asyncio" in sys.modules:
                        del sys.modules["redis.asyncio"]

    @pytest.mark.skip
    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_with_redis_import_error(
        self, mock_settings, mock_redis_available
    ):
        """Test event subscription when redis.asyncio import fails."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True
            mock_redis_module.from_url.return_value = mock_redis_client

            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")

            if "redis.asyncio" in sys.modules:
                del sys.modules["redis.asyncio"]

            service._redis_client = None

            async def subscriber():
                events = []
                async for event in service.subscribe_events():
                    events.append(event)
                    if len(events) == 1:
                        break
                return events

            async def publisher():
                await asyncio.sleep(0.1)
                await service.publish_event({"event": "local_test"})

            events, _ = await asyncio.gather(subscriber(), publisher())

            assert len(events) == 1
            assert events[0] == {"event": "local_test"}

    # Test subscribe_events method - Local mode tests

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_local_mode(self, mock_settings, mock_redis_unavailable):
        """Test event subscription in local mode."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        async def subscriber():
            events = []
            async for event in service.subscribe_events():
                events.append(event)
                if len(events) == 2:
                    break
            return events

        async def publisher():
            await asyncio.sleep(0.1)
            await service.publish_event({"event": "test1"})
            await service.publish_event({"event": "test2"})

        events, _ = await asyncio.gather(subscriber(), publisher())

        assert len(events) == 2
        assert events[0] == {"event": "test1"}
        assert events[1] == {"event": "test2"}

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_local_mode_cancellation(
        self, mock_settings, mock_redis_unavailable
    ):
        """Test event subscription cancellation in local mode."""
        with patch("mcpgateway.services.event_service.logger") as mock_logger:
            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")

            async def subscriber():
                async for event in service.subscribe_events():
                    pass

            async def publisher():
                await asyncio.sleep(0.1)
                await service.publish_event({"event": "test1"})

            sub_task = asyncio.create_task(subscriber())
            pub_task = asyncio.create_task(publisher())

            await pub_task
            await asyncio.sleep(0.2)

            sub_task.cancel()
            try:
                await sub_task
            except asyncio.CancelledError:
                pass

            await asyncio.sleep(0.1)

            mock_logger.debug.assert_called()
            error_message = str(mock_logger.debug.call_args)
            assert "Client disconnected" in error_message
            assert len(service._event_subscribers) == 0

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_subscribe_events_local_mode_queue_cleanup(
        self, mock_settings, mock_redis_unavailable
    ):
        """Test queue cleanup after local subscription ends."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        initial_subscriber_count = len(service._event_subscribers)

        async def subscriber():
            async for event in service.subscribe_events():
                if event["event"] == "test":
                    break

        async def publisher():
            await asyncio.sleep(0.1)
            await service.publish_event({"event": "test"})

        await asyncio.gather(subscriber(), publisher())

        assert len(service._event_subscribers) == initial_subscriber_count

    # Test event_generator method

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_event_generator_success(self, mock_settings, mock_redis_unavailable):
        """Test SSE event generator."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        async def generator_consumer():
            sse_events = []
            async for sse_event in service.event_generator():
                sse_events.append(sse_event)
                if len(sse_events) == 2:
                    break
            return sse_events

        async def publisher():
            await asyncio.sleep(0.1)
            await service.publish_event({"event": "sse1", "data": "value1"})
            await service.publish_event({"event": "sse2", "data": "value2"})

        sse_events, _ = await asyncio.gather(generator_consumer(), publisher())

        assert len(sse_events) == 2
        assert sse_events[0] == f'data: {orjson.dumps({"event": "sse1", "data": "value1"}).decode()}\n\n'
        assert sse_events[1] == f'data: {orjson.dumps({"event": "sse2", "data": "value2"}).decode()}\n\n'

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_event_generator_cancellation(self, mock_settings, mock_redis_unavailable):
        """Test SSE event generator cancellation."""
        with patch("mcpgateway.services.event_service.logger") as mock_logger:
            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")

            async def generator_consumer():
                async for sse_event in service.event_generator():
                    pass

            async def publisher():
                await asyncio.sleep(0.1)
                await service.publish_event({"event": "sse1"})

            gen_task = asyncio.create_task(generator_consumer())
            pub_task = asyncio.create_task(publisher())

            await pub_task
            await asyncio.sleep(0.2)

            gen_task.cancel()
            try:
                await gen_task
            except asyncio.CancelledError:
                pass

            await asyncio.sleep(0.1)

            mock_logger.info.assert_called()
            info_message = str(mock_logger.info.call_args)
            assert "Client disconnected from event stream" in info_message

    # Test shutdown method

    @pytest.mark.asyncio
    async def test_shutdown_with_redis_client(self, mock_settings, mock_redis_available):
        """Test shutdown with active Redis client - does not close shared client."""
        mock_redis_client = AsyncMock()

        async def mock_get_redis_client():
            return mock_redis_client

        with patch("mcpgateway.services.event_service.get_redis_client", mock_get_redis_client):
            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")
            await service.initialize()

            service._event_subscribers.append(asyncio.Queue())
            service._event_subscribers.append(asyncio.Queue())

            await service.shutdown()

            # Should clear reference but NOT close shared client
            assert service._redis_client is None
            assert len(service._event_subscribers) == 0

    @pytest.mark.asyncio
    async def test_shutdown_without_redis_client(self, mock_settings, mock_redis_unavailable):
        """Test shutdown without Redis client."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        service._event_subscribers.append(asyncio.Queue())
        service._event_subscribers.append(asyncio.Queue())

        await service.shutdown()

        assert len(service._event_subscribers) == 0

    @pytest.mark.asyncio
    async def test_shutdown_with_empty_subscribers(self, mock_settings, mock_redis_unavailable):
        """Test shutdown with no subscribers."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        await service.shutdown()
        assert len(service._event_subscribers) == 0

    # Integration tests

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_multiple_subscribers_receive_same_event(
        self, mock_settings, mock_redis_unavailable
    ):
        """Test multiple subscribers receive the same published event."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        subscriber_results = {1: None, 2: None, 3: None}

        async def subscriber(subscriber_id):
            async for event in service.subscribe_events():
                subscriber_results[subscriber_id] = event
                break

        async def publisher():
            await asyncio.sleep(0.2)
            await service.publish_event({"event": "broadcast", "data": "test"})

        await asyncio.gather(subscriber(1), subscriber(2), subscriber(3), publisher())

        assert all(
            event == {"event": "broadcast", "data": "test"}
            for event in subscriber_results.values()
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_publish_before_subscribe(self, mock_settings, mock_redis_unavailable):
        """Test that events published before subscription are not received."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        await service.publish_event({"event": "early_event"})

        async def subscriber():
            events = []
            async for event in service.subscribe_events():
                events.append(event)
                if len(events) == 1:
                    break
            return events

        async def publisher():
            await asyncio.sleep(0.1)
            await service.publish_event({"event": "later_event"})

        events, _ = await asyncio.gather(subscriber(), publisher())

        assert len(events) == 1
        assert events[0] == {"event": "later_event"}

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_complex_event_data(self, mock_settings, mock_redis_unavailable):
        """Test publishing and receiving complex event data structures."""
        from mcpgateway.services.event_service import EventService

        service = EventService("test:channel")

        complex_event = {
            "event": "complex",
            "nested": {
                "array": [1, 2, 3],
                "object": {"key": "value"},
                "null": None,
                "boolean": True,
            },
            "unicode": "测试 🎉",
        }

        async def subscriber():
            async for event in service.subscribe_events():
                return event

        async def publisher():
            await asyncio.sleep(0.1)
            await service.publish_event(complex_event)

        received_event, _ = await asyncio.gather(subscriber(), publisher())

        assert received_event == complex_event


def test_event_service_import_redis_check_failure(monkeypatch):
    """Ensure module handles redis discovery failure."""
    import sys

    original_find_spec = importlib.util.find_spec

    def _find_spec(name, *args, **kwargs):
        if name in {"redis", "redis.asyncio"}:
            raise ModuleNotFoundError("boom")
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec)
    sys.modules.pop("mcpgateway.services.event_service", None)

    module = importlib.import_module("mcpgateway.services.event_service")

    assert module.REDIS_AVAILABLE is False


@pytest.mark.asyncio
async def test_subscribe_events_redis_flow(monkeypatch):
    """Exercise Redis subscribe_events flow including non-message paths."""
    from mcpgateway.services.event_service import EventService

    class FakePubSub:
        def __init__(self):
            self._messages = [
                None,
                {"type": "subscribe"},
                {"type": "message", "data": orjson.dumps({"hello": "world"})},
            ]
            self.unsubscribed = False
            self.closed = False

        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            return self._messages.pop(0) if self._messages else None

        async def unsubscribe(self, _channel):
            self.unsubscribed = True

        async def aclose(self):
            self.closed = True

    fake_pubsub = FakePubSub()
    fake_client = MagicMock()
    fake_client.pubsub.return_value = fake_pubsub

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis")
        service._redis_client = object()

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.services.event_service.get_redis_client", AsyncMock(return_value=fake_client))
        monkeypatch.setattr("mcpgateway.services.event_service.asyncio.sleep", AsyncMock())

        agen = service.subscribe_events()
        event = await agen.__anext__()
        await agen.aclose()

        assert event == {"hello": "world"}
        assert fake_pubsub.unsubscribed is True
        assert fake_pubsub.closed is True


@pytest.mark.asyncio
async def test_subscribe_events_get_redis_client_none_falls_back_to_local(monkeypatch):
    """Exercise fallback_to_local path when get_redis_client returns None."""
    from mcpgateway.services.event_service import EventService

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis-none-client")
        service._redis_client = object()

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.services.event_service.get_redis_client", AsyncMock(return_value=None))

        agen = service.subscribe_events()
        task = asyncio.create_task(agen.__anext__())

        # Wait until the local queue is registered.
        while not service._event_subscribers:
            await asyncio.sleep(0)

        service._redis_client = None
        await service.publish_event({"event": "local"})

        event = await task
        await agen.aclose()

        assert event == {"event": "local"}


@pytest.mark.asyncio
async def test_subscribe_events_timeout_error_continues(monkeypatch):
    """Exercise the asyncio.TimeoutError branch during Redis polling."""
    from mcpgateway.services.event_service import EventService

    class FakePubSub:
        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            return None

        async def unsubscribe(self, _channel):
            return None

        async def aclose(self):
            return None

    fake_pubsub = FakePubSub()
    fake_client = MagicMock()
    fake_client.pubsub.return_value = fake_pubsub

    call_count = 0

    async def fake_wait_for(awaitable, timeout):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        await awaitable  # Ensure awaited to avoid warnings
        if call_count == 1:
            raise asyncio.TimeoutError()
        return {"type": "message", "data": orjson.dumps({"ok": True})}

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis-timeout")
        service._redis_client = object()

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.services.event_service.get_redis_client", AsyncMock(return_value=fake_client))
        monkeypatch.setattr("mcpgateway.services.event_service.asyncio.wait_for", fake_wait_for)

        agen = service.subscribe_events()
        event = await agen.__anext__()
        await agen.aclose()

        assert event == {"ok": True}


@pytest.mark.asyncio
async def test_subscribe_events_cancelled_error_is_logged(monkeypatch):
    """Exercise the asyncio.CancelledError branch for Redis subscriptions."""
    from mcpgateway.services.event_service import EventService

    class FakePubSub:
        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            return None

        async def unsubscribe(self, _channel):
            return None

        async def aclose(self):
            return None

    fake_client = MagicMock()
    fake_client.pubsub.return_value = FakePubSub()

    async def fake_wait_for(awaitable, timeout):  # noqa: ARG001
        await awaitable
        raise asyncio.CancelledError()

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis-cancel")
        service._redis_client = object()

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.services.event_service.get_redis_client", AsyncMock(return_value=fake_client))
        monkeypatch.setattr("mcpgateway.services.event_service.asyncio.wait_for", fake_wait_for)

        with patch("mcpgateway.services.event_service.logger") as mock_logger:
            agen = service.subscribe_events()
            with pytest.raises(asyncio.CancelledError):
                await agen.__anext__()
            await agen.aclose()

            mock_logger.debug.assert_called()


@pytest.mark.asyncio
async def test_subscribe_events_redis_exception_is_logged(monkeypatch):
    """Exercise the generic exception branch for Redis subscriptions."""
    from mcpgateway.services.event_service import EventService

    class FakePubSub:
        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            return None

        async def unsubscribe(self, _channel):
            return None

        async def aclose(self):
            return None

    fake_client = MagicMock()
    fake_client.pubsub.return_value = FakePubSub()

    async def fake_wait_for(awaitable, timeout):  # noqa: ARG001
        await awaitable
        raise Exception("Redis boom")

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis-error")
        service._redis_client = object()

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.services.event_service.get_redis_client", AsyncMock(return_value=fake_client))
        monkeypatch.setattr("mcpgateway.services.event_service.asyncio.wait_for", fake_wait_for)

        with patch("mcpgateway.services.event_service.logger") as mock_logger:
            agen = service.subscribe_events()
            with pytest.raises(Exception, match="Redis boom"):
                await agen.__anext__()
            await agen.aclose()

            mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_subscribe_events_cleanup_error_is_logged(monkeypatch):
    """Exercise the cleanup warning path when unsubscribing fails."""
    from mcpgateway.services.event_service import EventService

    class FakePubSub:
        def __init__(self):
            self._returned = False

        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            if self._returned:
                return None
            self._returned = True
            return {"type": "message", "data": orjson.dumps({"hello": "world"})}

        async def unsubscribe(self, _channel):
            raise Exception("Cleanup boom")

        async def aclose(self):
            return None

    fake_client = MagicMock()
    fake_client.pubsub.return_value = FakePubSub()

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis-cleanup")
        service._redis_client = object()

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.services.event_service.get_redis_client", AsyncMock(return_value=fake_client))

        with patch("mcpgateway.services.event_service.logger") as mock_logger:
            agen = service.subscribe_events()
            event = await agen.__anext__()
            await agen.aclose()

            assert event == {"hello": "world"}
            mock_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_subscribe_events_import_error_falls_back_to_local(monkeypatch):
    """Exercise ImportError handling during Redis subscribe setup."""
    from mcpgateway.services.event_service import EventService

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis-import-error")
        service._redis_client = object()

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.services.event_service.get_redis_client", AsyncMock(side_effect=ImportError("no redis")))

        with patch("mcpgateway.services.event_service.logger") as mock_logger:
            agen = service.subscribe_events()
            task = asyncio.create_task(agen.__anext__())

            while not service._event_subscribers:
                await asyncio.sleep(0)

            service._redis_client = None
            await service.publish_event({"event": "local"})

            event = await task
            await agen.aclose()

            assert event == {"event": "local"}
            mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_subscribe_events_redis_configured_without_client_exits(monkeypatch):
    """Exercise the branch where Redis is configured/available but the service has no client."""
    from mcpgateway.services.event_service import EventService

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:redis-no-client")

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)

        agen = service.subscribe_events()
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()


@pytest.mark.asyncio
async def test_event_generator_exits_when_subscribe_events_exits(monkeypatch):
    """Exercise event_generator's empty-loop path when subscribe_events produces nothing."""
    from mcpgateway.services.event_service import EventService

    with patch("mcpgateway.services.event_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        service = EventService("test:event-gen-empty")

        monkeypatch.setattr("mcpgateway.services.event_service.REDIS_AVAILABLE", True)

        agen = service.event_generator()
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()
