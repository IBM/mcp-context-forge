# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/services/test_event_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

Description:

Comprehensive test suite for EventService with maximum code coverage.

"""

import asyncio
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
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
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True
            mock_redis_module.from_url.return_value = mock_redis_client

            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")

            assert service.channel_name == "test:channel"
            assert service.redis_url == "redis://localhost:6379"
            assert service._redis_client is not None
            assert service._event_subscribers == []
            mock_redis_module.from_url.assert_called_once_with("redis://localhost:6379")
            mock_redis_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_with_redis_connection_failure(self, mock_settings, mock_redis_available):
        """Test initialization when Redis connection fails."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                mock_redis_module.from_url.side_effect = Exception("Connection failed")

                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")

                assert service._redis_client is None
                mock_logger.warning.assert_called_once()
                assert "Failed to initialize Redis" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_init_with_redis_ping_failure(self, mock_settings, mock_redis_available):
        """Test initialization when Redis ping fails."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                mock_redis_client = MagicMock()
                mock_redis_client.ping.side_effect = Exception("Ping failed")
                mock_redis_module.from_url.return_value = mock_redis_client

                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")

                assert service._redis_client is None
                mock_logger.warning.assert_called_once()

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
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True
            mock_redis_client.publish = MagicMock()
            mock_redis_module.from_url.return_value = mock_redis_client

            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")
            event_data = {"event": "test_event", "data": "test_data"}

            with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
                await service.publish_event(event_data)

                mock_to_thread.assert_called_once()
                call_args = mock_to_thread.call_args[0]
                assert call_args[0] == mock_redis_client.publish
                assert call_args[1] == "test:channel"
                assert json.loads(call_args[2]) == event_data

    @pytest.mark.asyncio
    async def test_publish_event_with_redis_failure_fallback_to_local(
        self, mock_settings, mock_redis_available
    ):
        """Test event publishing falls back to local queues when Redis fails."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            with patch("mcpgateway.services.event_service.logger") as mock_logger:
                mock_redis_client = MagicMock()
                mock_redis_client.ping.return_value = True
                mock_redis_module.from_url.return_value = mock_redis_client

                from mcpgateway.services.event_service import EventService

                service = EventService("test:channel")

                queue1 = asyncio.Queue()
                queue2 = asyncio.Queue()
                service._event_subscribers.append(queue1)
                service._event_subscribers.append(queue2)

                event_data = {"event": "test_event", "data": "test_data"}

                with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
                    mock_to_thread.side_effect = Exception("Redis publish failed")
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
        assert sse_events[0] == f'data: {json.dumps({"event": "sse1", "data": "value1"})}\n\n'
        assert sse_events[1] == f'data: {json.dumps({"event": "sse2", "data": "value2"})}\n\n'

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
        """Test shutdown with active Redis client."""
        with patch("mcpgateway.services.event_service.redis") as mock_redis_module:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True
            mock_redis_client.close = MagicMock()
            mock_redis_module.from_url.return_value = mock_redis_client

            from mcpgateway.services.event_service import EventService

            service = EventService("test:channel")

            service._event_subscribers.append(asyncio.Queue())
            service._event_subscribers.append(asyncio.Queue())

            await service.shutdown()

            mock_redis_client.close.assert_called_once()
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
