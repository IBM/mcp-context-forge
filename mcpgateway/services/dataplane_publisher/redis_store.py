# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dataplane_publisher/redis_store.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Redis client operations for publisher locking and payload persistence.
"""

# Standard
import logging
from typing import Any, Final

# Third-Party
import msgpack

# First-Party
from mcpgateway.services.dataplane_publisher.dataplane_schema import UserConfig
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)

PUBLISHER_LOCK_KEY = "mcpgw:dataplane_publisher:lock"
_USER_CONFIG_KEY: Final = "UserConfig"

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""


class DataplaneRedisStore:
    """Redis lock and write operations for one publisher worker."""

    def __init__(self, worker_id: str) -> None:
        """Bind the store to a specific worker identity."""
        self._worker_id = worker_id

    async def try_acquire_lock(self, lock_ttl: int) -> tuple[Any, bool]:
        """Get the Redis client and attempt to acquire the publisher lock.

        Args:
            lock_ttl: Lock expiry in seconds.

        Returns:
            Tuple of (redis client or None, acquired).
            When redis is None the lock was not acquired.
            When acquired is False another worker holds the lock.
        """
        redis = await get_redis_client()
        if redis is None:
            logger.error("Redis client is unavailable, skipping cycle")
            return None, False
        acquired = await redis.set(PUBLISHER_LOCK_KEY, self._worker_id, nx=True, ex=lock_ttl)
        if not acquired:
            logger.debug("Another worker holds publisher lock, skipping cycle")
        return redis, bool(acquired)

    async def release_lock(self, redis: Any) -> None:
        """Release the lock if this worker still owns it."""
        try:
            await redis.eval(_RELEASE_SCRIPT, 1, PUBLISHER_LOCK_KEY, self._worker_id)
        except Exception as exc:
            logger.warning("Failed to release publisher lock: %s", exc)

    async def write_payload(self, redis: Any, payload: dict[str, UserConfig], ttl: int) -> None:
        """Serialise and write all UserConfig records in a single pipeline.

        Args:
            redis: Active Redis client.
            payload: UserConfig records keyed by user UUID.
            ttl: Key expiry in seconds.
        """
        pipe = redis.pipeline()
        for user_id, config in payload.items():
            key = msgpack.dumps((_USER_CONFIG_KEY, user_id), use_bin_type=True)
            value = msgpack.dumps(config, use_bin_type=True)
            pipe.set(key, value, ex=ttl)
        await pipe.execute()
        logger.info("Published %d UserConfig records", len(payload))
