# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/event_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
import uuid

# Third-Party
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

class EventService:
    """
    Generic Event Service handling Redis PubSub with Local Queue fallback.
    Replicates the logic from GatewayService for use in other services.
    """

    def __init__(self, channel_name: str) -> None:
        """
        Initialize the Event Service.
        
        Args:
            channel_name: The specific Redis channel to use (e.g., 'mcpgateway:tool_events')
                          to ensure separation of services.
        """
        self.channel_name = channel_name
        self._event_subscribers: List[asyncio.Queue] = []
        
        self.redis_url = settings.redis_url if settings.cache_type == "redis" else None
        self._redis_client: Optional[Any] = None

        if self.redis_url and REDIS_AVAILABLE:
            try:
                self._redis_client = redis.from_url(self.redis_url)
                # Quick ping to verify connection
                self._redis_client.ping()
            except Exception as e:
                logger.warning(f"Failed to initialize Redis for EventService ({channel_name}): {e}")
                self._redis_client = None

    async def publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish event to Redis or fallback to local subscribers.
        """
        if self._redis_client:
            try:
                await asyncio.to_thread(self._redis_client.publish, self.channel_name, json.dumps(event))
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
        """
        Subscribe to events. Yields events as they are published.
        """
        # If Redis Available
        if self._redis_client:
            try:
                # Import asyncio version of redis here to avoid top-level dependency issues
                import redis.asyncio as aioredis
                
                # Create a dedicated async connection for this subscription
                client = aioredis.from_url(self.redis_url, decode_responses=True)
                pubsub = client.pubsub()
                
                await pubsub.subscribe(self.channel_name)
                
                try:
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            # Yield the data portion
                            yield json.loads(message["data"])
                except asyncio.CancelledError:
                    # Handle client disconnection
                    raise
                except Exception as e:
                    logger.error(f"Redis subscription error on {self.channel_name}: {e}")
                    raise
                finally:
                    # Cleanup
                    try:
                        await pubsub.unsubscribe(self.channel_name)
                        await client.aclose()
                    except Exception as e:
                        logger.warning(f"Error closing Redis subscription: {e}")
            except ImportError:
                logger.error("Redis is configured but redis-py does not support asyncio or is not installed.")
                # Fallthrough to queue mode if import fails
        
        # Local Queue (Redis not available or import failed)
        if not (self.redis_url and REDIS_AVAILABLE):
            queue: asyncio.Queue = asyncio.Queue()
            self._event_subscribers.append(queue)
            try:
                while True:
                    event = await queue.get()
                    yield event
            except asyncio.CancelledError:
                raise
            finally:
                if queue in self._event_subscribers:
                    self._event_subscribers.remove(queue)

    async def shutdown(self):
        """Cleanup resources."""
        if self._redis_client:
            # Sync client doesn't always need explicit close in this context, 
            # but good practice to clear references.
            self._redis_client.close()
        self._event_subscribers.clear()