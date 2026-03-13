# -*- coding: utf-8 -*-
"""A cache implementation to share information across plugins for LLMGuard. Example - sharing of vault between Anonymizer and
Deanonymizer defined in two plugins

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads redis client for caching, updates, retrieves and deletes cache.
"""

# Standard
import os

# Third-Party
import orjson
from prometheus_client import Counter
import redis.asyncio as aioredis

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Prometheus metrics for error tracking
llm_guard_cache_errors_total = Counter(
    "llm_guard_cache_errors_total",
    "Total number of cache errors by type",
    labelnames=["error_type", "operation"],
)

# Initialize redis host and client values
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", "6379"))


class CacheTTLDict(dict):
    """Base class that implements caching logic for vault caching across plugins.

    Attributes:
        cache_ttl: Cache time to live in seconds
        cache: Redis client to connect to database for caching
    """

    def __init__(self, ttl: int = 0) -> None:
        """init block for cache. This initializes a redis client.

        Args:
            ttl: Time to live in seconds for cache
        """
        self.cache_ttl = ttl
        self.cache = aioredis.from_url(f"redis://{redis_host}:{redis_port}")
        logger.info("Cache Initialization: %s", self.cache)

    async def update_cache(self, key: int = None, value: list = None) -> tuple[bool, bool]:
        """Takes in key and value for caching in redis. It sets expiry time for the key.
        And redis, by itself takes care of deleting that key from cache after ttl has been reached.

        Args:
            key: The id of vault in string
            value: The tuples in the vault (List[Tuple] format)

        Returns:
            tuple[bool, bool]: A tuple containing (success_set, success_expiry) booleans.
        """
        try:
            serialized_obj = orjson.dumps(value)
        except TypeError as e:
            # Non-JSON types in vault will break deanonymization later
            logger.error("Cache serialization failed for key %s - vault sharing disabled: %s", key, e)
            llm_guard_cache_errors_total.labels(error_type="serialization_error", operation="update").inc()
            return False, False
        # Log key and size only - serialized_obj may contain PII
        logger.debug("Updating cache for key: %s, size: %d bytes", key, len(serialized_obj))
        async with self.cache.pipeline() as pipe:
            await pipe.set(key, serialized_obj)
            await pipe.expire(key, self.cache_ttl)
            results = await pipe.execute()
            success_set, success_expiry = results[0], results[1]
            if success_set:
                logger.debug("Cache set successful for key: %s", key)
            else:
                logger.error("Cache set failed for key: %s", key)
            if success_expiry:
                logger.debug("Cache expiry set successfully for key: %s", key)
            else:
                logger.error("Failed to set cache expiration")
            return success_set, success_expiry

    async def retrieve_cache(self, key: int = None) -> list | None:
        """Retrieves cache for a key value

        Args:
            key: The id of vault in string

        Returns:
            list | None: The retrieved object from cache (List[Tuple] for vault) or None if not found.
        """
        value = await self.cache.get(key)
        if value:
            try:
                retrieved_obj = orjson.loads(value)
                # Vault data must be List[List] -> convert to List[Tuple]
                if not isinstance(retrieved_obj, list):
                    # Unexpected shape - treat as cache miss to avoid downstream crash
                    logger.warning("Cache data for key %s has unexpected type %s, treating as miss", key, type(retrieved_obj).__name__)
                    llm_guard_cache_errors_total.labels(error_type="invalid_type", operation="retrieve").inc()
                    await self.cache.delete(key)
                    return None
                retrieved_obj = self._convert_to_list_of_tuples(retrieved_obj)
                logger.debug("Cache hit for key: %s, items: %d", key, len(retrieved_obj))
                return retrieved_obj
            except orjson.JSONDecodeError as e:
                logger.error("Cache retrieval failed - invalid JSON for id: %s: %s", key, e)
                llm_guard_cache_errors_total.labels(error_type="json_decode_error", operation="retrieve").inc()
                # Delete corrupted entry to avoid repeated error logs
                await self.cache.delete(key)
                return None
        else:
            logger.debug("Cache miss for id: %s", key)
            return None

    def _convert_to_list_of_tuples(self, obj: list) -> list:
        """Converts List[List[str]] to List[Tuple[str, ...]] for vault compatibility.

        The Vault class expects List[Tuple] for _tuples attribute.
        JSON serialization converts tuples to lists, so we convert the immediate
        children back to tuples. Vault tuples are flat string tuples like
        ('original_text', 'entity_type', 'placeholder'), so no deep recursion needed.
        """
        return [tuple(item) if isinstance(item, list) else item for item in obj]

    async def delete_cache(self, key: int = None) -> None:
        """Deletes cache for a key value

        Args:
            key: The id of vault in string
        """
        logger.info("Deleting cache for key : %s", key)
        deleted_count = await self.cache.delete(key)
        exists_count = await self.cache.exists(key)
        if deleted_count == 1 and exists_count == 0:
            logger.info("Cache deleted successfully for key: %s", key)
        else:
            logger.info("Unsuccessful cache deletion: %s", key)
