# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/redis_pool_backend.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Redis Backend for Distributed Pool State Management.

This module provides Redis-based backend for session pool state synchronization
across multiple gateway instances, enabling horizontal scaling and high availability.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

logger = logging.getLogger(__name__)


class RedisPoolBackend:
    """Redis backend for distributed pool state management.
    
    Provides distributed state synchronization, pub/sub event broadcasting,
    and distributed locking for pool operations across multiple gateway instances.
    
    Features:
        - Distributed pool state storage
        - Pub/sub for real-time event broadcasting
        - Distributed locks for coordinated operations
        - Automatic state expiration and cleanup
        - Connection pooling and retry logic
    
    Attributes:
        redis_url: Redis connection URL
        prefix: Key prefix for namespacing
        pool_size: Connection pool size
        timeout: Operation timeout in seconds
    """

    def __init__(
        self,
        redis_url: str,
        prefix: str = "mcpgateway:pool:",
        pool_size: int = 10,
        timeout: int = 5,
        retry_attempts: int = 3,
        retry_delay: float = 0.5
    ):
        """Initialize Redis pool backend.
        
        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
            prefix: Key prefix for namespacing
            pool_size: Connection pool size
            timeout: Operation timeout in seconds
            retry_attempts: Number of retry attempts for failed operations
            retry_delay: Delay between retries in seconds
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis package is required for Redis backend. "
                "Install with: pip install redis[hiredis]"
            )
        
        self.redis_url = redis_url
        self.prefix = prefix
        self.pool_size = pool_size
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        
        self._client: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._connected = False
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Initialized Redis pool backend "
            f"(url={redis_url}, prefix={prefix}, pool_size={pool_size})"
        )

    async def connect(self) -> None:
        """Connect to Redis and initialize pub/sub."""
        if self._connected:
            logger.debug("Already connected to Redis")
            return
        
        try:
            # Create Redis client with connection pool
            self._client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=self.pool_size,
                socket_timeout=self.timeout,
                socket_connect_timeout=self.timeout
            )
            
            # Test connection
            await self._client.ping()
            
            # Initialize pub/sub
            self._pubsub = self._client.pubsub()
            await self._pubsub.subscribe(f"{self.prefix}events")
            
            self._connected = True
            logger.info("Connected to Redis successfully")
        
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Redis and cleanup resources."""
        if not self._connected:
            return
        
        try:
            if self._pubsub:
                await self._pubsub.unsubscribe(f"{self.prefix}events")
                await self._pubsub.close()
            
            if self._client:
                await self._client.close()
            
            self._connected = False
            logger.info("Disconnected from Redis")
        
        except Exception as e:
            logger.error(f"Error disconnecting from Redis: {e}")

    async def _retry_operation(self, operation, *args, **kwargs):
        """Retry an operation with exponential backoff.
        
        Args:
            operation: Async function to retry
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation
            
        Returns:
            Result of operation if successful
            
        Raises:
            Exception: If all retry attempts fail
        """
        last_error = None
        
        for attempt in range(self.retry_attempts):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.retry_attempts - 1:
                    delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"Operation failed (attempt {attempt + 1}/{self.retry_attempts}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
        
        logger.error(f"Operation failed after {self.retry_attempts} attempts")
        raise last_error

    async def save_pool_state(self, pool_id: str, state: Dict[str, Any]) -> None:
        """Save pool state to Redis.
        
        Args:
            pool_id: Unique pool identifier
            state: Pool state dictionary
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        key = f"{self.prefix}state:{pool_id}"
        
        async def _save():
            # Convert state to JSON-serializable format
            serialized_state = {
                k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in state.items()
            }
            
            # Save as hash
            await self._client.hset(key, mapping=serialized_state)
            
            # Set expiration (1 hour)
            await self._client.expire(key, 3600)
            
            logger.debug(f"Saved pool state for {pool_id}")
        
        await self._retry_operation(_save)

    async def get_pool_state(self, pool_id: str) -> Optional[Dict[str, Any]]:
        """Get pool state from Redis.
        
        Args:
            pool_id: Unique pool identifier
            
        Returns:
            Pool state dictionary if found, None otherwise
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        key = f"{self.prefix}state:{pool_id}"
        
        async def _get():
            state = await self._client.hgetall(key)
            if not state:
                return None
            
            # Deserialize JSON values
            deserialized_state = {}
            for k, v in state.items():
                try:
                    deserialized_state[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    deserialized_state[k] = v
            
            logger.debug(f"Retrieved pool state for {pool_id}")
            return deserialized_state
        
        return await self._retry_operation(_get)

    async def delete_pool_state(self, pool_id: str) -> None:
        """Delete pool state from Redis.
        
        Args:
            pool_id: Unique pool identifier
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        key = f"{self.prefix}state:{pool_id}"
        
        async def _delete():
            await self._client.delete(key)
            logger.debug(f"Deleted pool state for {pool_id}")
        
        await self._retry_operation(_delete)

    async def acquire_lock(
        self,
        pool_id: str,
        timeout: int = 10,
        blocking_timeout: Optional[int] = None
    ) -> bool:
        """Acquire distributed lock for pool operations.
        
        Args:
            pool_id: Unique pool identifier
            timeout: Lock expiration timeout in seconds
            blocking_timeout: Maximum time to wait for lock (None = non-blocking)
            
        Returns:
            True if lock acquired, False otherwise
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        lock_key = f"{self.prefix}lock:{pool_id}"
        lock_value = f"{asyncio.current_task().get_name()}:{datetime.now(timezone.utc).isoformat()}"
        
        async def _acquire():
            if blocking_timeout is None:
                # Non-blocking acquire
                result = await self._client.set(
                    lock_key,
                    lock_value,
                    nx=True,  # Only set if not exists
                    ex=timeout  # Expiration time
                )
                return bool(result)
            else:
                # Blocking acquire with timeout
                start_time = asyncio.get_event_loop().time()
                while True:
                    result = await self._client.set(
                        lock_key,
                        lock_value,
                        nx=True,
                        ex=timeout
                    )
                    if result:
                        return True
                    
                    # Check if timeout exceeded
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= blocking_timeout:
                        return False
                    
                    # Wait before retry
                    await asyncio.sleep(0.1)
        
        result = await self._retry_operation(_acquire)
        if result:
            logger.debug(f"Acquired lock for pool {pool_id}")
        else:
            logger.debug(f"Failed to acquire lock for pool {pool_id}")
        return result

    async def release_lock(self, pool_id: str) -> None:
        """Release distributed lock.
        
        Args:
            pool_id: Unique pool identifier
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        lock_key = f"{self.prefix}lock:{pool_id}"
        
        async def _release():
            await self._client.delete(lock_key)
            logger.debug(f"Released lock for pool {pool_id}")
        
        await self._retry_operation(_release)

    async def publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish pool event to Redis pub/sub.
        
        Args:
            event_type: Type of event (e.g., "pool.created", "pool.drained")
            data: Event data dictionary
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data
        }
        
        async def _publish():
            await self._client.publish(
                f"{self.prefix}events",
                json.dumps(event)
            )
            logger.debug(f"Published event: {event_type}")
        
        await self._retry_operation(_publish)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to pool events from Redis pub/sub.
        
        Yields:
            Event dictionaries as they are received
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        if not self._pubsub:
            raise RuntimeError("Pub/sub not initialized")
        
        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        logger.debug(f"Received event: {event.get('type')}")
                        yield event
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode event: {e}")
        except Exception as e:
            logger.error(f"Error in event subscription: {e}")
            raise

    async def get_all_pool_ids(self) -> List[str]:
        """Get list of all pool IDs stored in Redis.
        
        Returns:
            List of pool IDs
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        pattern = f"{self.prefix}state:*"
        
        async def _get_ids():
            keys = []
            async for key in self._client.scan_iter(match=pattern):
                # Extract pool_id from key
                pool_id = key.replace(f"{self.prefix}state:", "")
                keys.append(pool_id)
            return keys
        
        return await self._retry_operation(_get_ids)

    async def increment_counter(self, counter_name: str, amount: int = 1) -> int:
        """Increment a distributed counter.
        
        Args:
            counter_name: Name of the counter
            amount: Amount to increment by
            
        Returns:
            New counter value
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        key = f"{self.prefix}counter:{counter_name}"
        
        async def _increment():
            value = await self._client.incrby(key, amount)
            return value
        
        return await self._retry_operation(_increment)

    async def get_counter(self, counter_name: str) -> int:
        """Get current value of a distributed counter.
        
        Args:
            counter_name: Name of the counter
            
        Returns:
            Current counter value
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        key = f"{self.prefix}counter:{counter_name}"
        
        async def _get():
            value = await self._client.get(key)
            return int(value) if value else 0
        
        return await self._retry_operation(_get)

    async def set_expiring_value(
        self,
        key_name: str,
        value: str,
        ttl: int
    ) -> None:
        """Set a value with expiration time.
        
        Args:
            key_name: Key name
            value: Value to store
            ttl: Time to live in seconds
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        key = f"{self.prefix}temp:{key_name}"
        
        async def _set():
            await self._client.setex(key, ttl, value)
        
        await self._retry_operation(_set)

    async def get_value(self, key_name: str) -> Optional[str]:
        """Get a stored value.
        
        Args:
            key_name: Key name
            
        Returns:
            Stored value if found, None otherwise
        """
        if not self._connected:
            raise RuntimeError("Not connected to Redis")
        
        key = f"{self.prefix}temp:{key_name}"
        
        async def _get():
            return await self._client.get(key)
        
        return await self._retry_operation(_get)

    async def health_check(self) -> bool:
        """Check if Redis connection is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        if not self._connected:
            return False
        
        try:
            await self._client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get Redis backend statistics.
        
        Returns:
            Dictionary with connection stats
        """
        return {
            "connected": self._connected,
            "redis_url": self.redis_url,
            "prefix": self.prefix,
            "pool_size": self.pool_size,
            "timeout": self.timeout,
            "retry_attempts": self.retry_attempts,
        }


# Singleton instance
_redis_backend: Optional[RedisPoolBackend] = None


async def get_redis_backend() -> Optional[RedisPoolBackend]:
    """Get or create Redis backend singleton.
    
    Returns:
        RedisPoolBackend instance if Redis is enabled, None otherwise
    """
    global _redis_backend
    
    if _redis_backend is None:
        from mcpgateway.config import settings
        
        if settings.redis_enabled:
            _redis_backend = RedisPoolBackend(
                redis_url=settings.redis_url,
                prefix=settings.redis_pool_prefix
            )
            await _redis_backend.connect()
    
    return _redis_backend


async def shutdown_redis_backend() -> None:
    """Shutdown Redis backend singleton."""
    global _redis_backend
    
    if _redis_backend:
        await _redis_backend.disconnect()
        _redis_backend = None

# Made with Bob
