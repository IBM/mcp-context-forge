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
import redis

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize redis host and client values
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))


class CacheTTLDict(dict):
    """Base class that implements caching logic for vault caching across plugins.

    Attributes:
        cache_ttl: Cache time to live in seconds
        cache: Redis client to connect to database for caching
    """

    def __init__(self, ttl: int = 0) -> None:
        """init block for cache. This initializes a redit client.

        Args:
            ttl: Time to live in seconds for cache
        """
        self.cache_ttl = ttl
        self.cache = redis.Redis(host=redis_host, port=redis_port)
        logger.info(f"Cache Initialization: {self.cache}")

    def update_cache(self, key: int = None, value: list = None) -> tuple[bool, bool]:
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
            logger.error(f"Cache serialization failed for key {key} - vault sharing disabled: {e}")
            return False, False
        # Log key and size only - serialized_obj may contain PII
        logger.debug(f"Updating cache for key: {key}, size: {len(serialized_obj)} bytes")
        success_set = self.cache.set(key, serialized_obj)
        if success_set:
            logger.debug(f"Cache set successful for key: {key}")
        else:
            logger.error(f"Cache set failed for key: {key}")
        success_expiry = self.cache.expire(key, self.cache_ttl)
        if success_expiry:
            logger.debug(f"Cache expiry set successfully for key: {key}")
        else:
            logger.error("Failed to set cache expiration")
        return success_set, success_expiry

    def retrieve_cache(self, key: int = None) -> list | None:
        """Retrieves cache for a key value

        Args:
            key: The id of vault in string

        Returns:
            list | None: The retrieved object from cache (List[Tuple] for vault) or None if not found.
        """
        value = self.cache.get(key)
        if value:
            try:
                retrieved_obj = orjson.loads(value)
                # Vault data must be List[List] -> convert to List[Tuple]
                if not isinstance(retrieved_obj, list):
                    # Unexpected shape - treat as cache miss to avoid downstream crash
                    logger.warning(f"Cache data for key {key} has unexpected type {type(retrieved_obj).__name__}, treating as miss")
                    self.cache.delete(key)
                    return None
                retrieved_obj = self._convert_to_list_of_tuples(retrieved_obj)
                logger.debug(f"Cache hit for key: {key}, items: {len(retrieved_obj)}")
                return retrieved_obj
            except orjson.JSONDecodeError as e:
                logger.error(f"Cache retrieval failed - invalid JSON for id: {key}: {e}")
                # Delete corrupted entry to avoid repeated error logs
                self.cache.delete(key)
                return None
        else:
            logger.debug(f"Cache miss for id: {key}")
            return None

    def _convert_to_list_of_tuples(self, obj: list) -> list:
        """Converts List[List[str]] to List[Tuple[str, ...]] for vault compatibility.

        The Vault class expects List[Tuple] for _tuples attribute.
        JSON serialization converts tuples to lists, so we convert the immediate
        children back to tuples. Vault tuples are flat string tuples like
        ('original_text', 'entity_type', 'placeholder'), so no deep recursion needed.
        """
        return [tuple(item) if isinstance(item, list) else item for item in obj]

    def delete_cache(self, key: int = None) -> None:
        """Deletes cache for a key value

        Args:
            key: The id of vault in string
        """
        logger.info(f"Deleting cache for key : {key}")
        deleted_count = self.cache.delete(key)
        if deleted_count == 1 and self.cache.exists(key) == 0:
            logger.info(f"Cache deleted successfully for key: {key}")
        else:
            logger.info(f"Unsuccessful cache deletion: {key}")
