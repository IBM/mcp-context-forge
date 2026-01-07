# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/event_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Authors: Keval Mahajan

Description:
    This module implements a Centralized Event Service designed to decouple event
    producers from consumers within the MCP Gateway architecture for various services
    such as gateway_service, tool_service, and more.

    - Primary Transport (Redis): Uses Redis Pub/Sub for distributed event
      broadcasting. This allows multiple Gateway instances (scaled horizontally)
      to share events.
    - Fallback Transport (Local Queue): Uses `asyncio.Queue` for in-memory
      communication. This activates automatically if Redis is unavailable or
      misconfigured, ensuring the application remains functional in a single-node
      development environment.

Usage Guide:

    1. Initialization
       Instantiate the service with a unique channel name. This acts as the "Topic".

       ```python
       from mcpgateway.services.event_service import EventService

       # Create a service instance for tool execution events
       tool_events = EventService(channel_name="mcpgateway:tools")
       ```

    2. Publishing Events (Producer)
       Any part of the application can publish a dictionary to the channel.

       ```python
       await tool_events.publish_event({
           "event": "tool_start",
           "tool_name": "calculator",
           "timestamp": datetime.now().isoformat()
       })
       ```

    3. Subscribing to Events (Consumer)
       Use an async for-loop to listen to the stream. This generator yields
       events as they arrive.

       ```python
       async for event in tool_events.subscribe_events():
           print(f"Received event: {event['event']}")
           # Process event...
       ```
"""

# Standard
import asyncio
import importlib.util
from typing import Any, AsyncGenerator, Dict, List, Optional

# Third-Party
import orjson

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.redis_client import get_redis_client

REDIS_AVAILABLE = importlib.util.find_spec("redis.asyncio") is not None

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class EventService:
    """Generic Event Service handling Redis PubSub with Local Queue fallback.

    Replicates the logic from GatewayService for use in other services. It attempts
    to connect to Redis for a distributed event bus. If Redis is unavailable or
    configured to perform locally, it falls back to asyncio.Queue for in-process
    communication.

    Attributes:
        channel_name (str): The specific Redis/Queue channel identifier.
        redis_url (Optional[str]): The URL for the Redis connection.
    """

    def __init__(self, channel_name: str) -> None:
        """Initialize the Event Service.

        Args:
            channel_name: The specific Redis channel to use (e.g., 'mcpgateway:tool_events')
                to ensure separation of services.

        Example:
            >>> service = EventService("test:channel")
            >>> service.channel_name
            'test:channel'
        """
        self.channel_name = channel_name
        self._event_subscribers: List[asyncio.Queue] = []

        self.redis_url = settings.redis_url if settings.cache_type == "redis" else None
        self._redis_client: Optional[Any] = None
        # Redis client is set in initialize() via the shared factory

    async def initialize(self) -> None:
        """Initialize the event service with shared Redis client.

        Should be called during application startup to get the shared Redis client.
        """
        if self.redis_url and REDIS_AVAILABLE:
            try:
                self._redis_client = await get_redis_client()
                if self._redis_client:
                    logger.info(f"EventService ({self.channel_name}) connected to Redis")
            except Exception as e:
                logger.warning(f"Failed to initialize Redis for EventService ({self.channel_name}): {e}")
                self._redis_client = None

    async def publish_event(self, event: Dict[str, Any]) -> None:
        """Publish event to Redis or fallback to local subscribers.

        If a Redis client is active, the event is serialized to JSON and published
        to the configured channel. If Redis fails or is inactive, the event is
        pushed to all registered local asyncio queues.

        Args:
            event: A dictionary containing the event data to be published.

        Example:
            >>> import asyncio
            >>> async def test_pub():
            ...     # Force local mode for test
            ...     service = EventService("test:pub")
            ...     service._redis_client = None
            ...     # Create a listener
            ...     queue = asyncio.Queue()
            ...     service._event_subscribers.append(queue)
            ...
            ...     await service.publish_event({"type": "test", "data": 123})
            ...     return await queue.get()
            >>> asyncio.run(test_pub())
            {'type': 'test', 'data': 123}
        """
        if self._redis_client:
            try:
                await self._redis_client.publish(self.channel_name, orjson.dumps(event))
            except Exception as e:
                logger.error(f"Failed to publish event to Redis channel {self.channel_name}: {e}")
                # Fallback: push to local queues if Redis fails
                for queue in self._event_subscribers:
                    await queue.put(event)
        else:
            # Local only (single worker or file-lock mode)
            for queue in self._event_subscribers:
                await queue.put(event)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to events. Yields events as they are published.

        If Redis is available, this creates a dedicated async Redis connection
        and yields messages from the PubSub channel. If Redis is not available,
        it creates a local asyncio.Queue, adds it to the subscriber list, and
        yields items put into that queue.

        Yields:
            Dict[str, Any]: The deserialized event data.

        Raises:
            asyncio.CancelledError: If the async task is cancelled.
            Exception: For underlying Redis connection errors.

        Example:
            >>> import asyncio
            >>> async def test_sub():
            ...     service = EventService("test:sub")
            ...     service._redis_client = None # Force local mode
            ...
            ...     # Producer task
            ...     async def produce():
            ...         await asyncio.sleep(0.1)
            ...         await service.publish_event({"msg": "hello"})
            ...
            ...     # Consumer task
            ...     async def consume():
            ...         async for event in service.subscribe_events():
            ...             return event
            ...
            ...     # Run both
            ...     _, event = await asyncio.gather(produce(), consume())
            ...     return event
            >>> # asyncio.run(test_sub())
            {'msg': 'hello'}
        """

        fallback_to_local = False

        if self._redis_client:

            try:
                # Get shared Redis client from factory
                # PubSub uses the client's connection pool but creates dedicated subscription
                client = await get_redis_client()
                if not client:
                    fallback_to_local = True
                else:
                    pubsub = client.pubsub()

                    await pubsub.subscribe(self.channel_name)

                    try:
                        async for message in pubsub.listen():
                            if message["type"] == "message":
                                # Yield the data portion
                                yield orjson.loads(message["data"])
                    except asyncio.CancelledError:
                        # Handle client disconnection
                        logger.debug(f"Client disconnected from Redis subscription: {self.channel_name}")
                        raise
                    except Exception as e:
                        logger.error(f"Redis subscription error on {self.channel_name}: {e}")
                        raise
                    finally:
                        # Cleanup pubsub only (don't close shared client)
                        try:
                            await pubsub.unsubscribe(self.channel_name)
                            await pubsub.aclose()
                        except Exception as e:
                            logger.warning(f"Error closing Redis subscription: {e}")
            except ImportError:
                fallback_to_local = True
                logger.error("Redis is configured but redis-py does not support asyncio or is not installed.")
                # Fallthrough to queue mode if import fails

        # Local Queue (Redis not available or import failed)
        if fallback_to_local or not (self.redis_url and REDIS_AVAILABLE):
            queue: asyncio.Queue = asyncio.Queue()
            self._event_subscribers.append(queue)
            try:
                while True:
                    event = await queue.get()
                    yield event
            except asyncio.CancelledError:
                logger.debug(f"Client disconnected from local event subscription: {self.channel_name}")
                raise
            finally:
                if queue in self._event_subscribers:
                    self._event_subscribers.remove(queue)

    async def event_generator(self) -> AsyncGenerator[str, None]:
        """Generates Server-Sent Events (SSE) formatted strings.

        This is a convenience wrapper around `subscribe_events` designed for
        direct use with streaming HTTP responses (e.g., FastAPI's StreamingResponse).

        Yields:
            str: A string formatted as an SSE message: 'data: {...}\\n\\n'

        Raises:
            asyncio.CancelledError: If the client disconnects and the streaming
                task is cancelled.
        """
        try:
            async for event in self.subscribe_events():
                # Serialize the dictionary to a JSON string and format as SSE
                yield f"data: {orjson.dumps(event).decode()}\n\n"
        except asyncio.CancelledError:
            # Handle client disconnection gracefully
            logger.info(f"Client disconnected from event stream: {self.channel_name}")
            raise

    async def shutdown(self):
        """Cleanup resources.

        Clears local subscribers. The shared Redis client is managed by the factory.

        Example:
            >>> import asyncio
            >>> async def test_shutdown():
            ...     service = EventService("test:shutdown")
            ...     await service.shutdown()
            ...     return len(service._event_subscribers) == 0
            >>> asyncio.run(test_shutdown())
            True
        """
        # Don't close the shared Redis client - it's managed by redis_client.py
        self._redis_client = None
        self._event_subscribers.clear()
