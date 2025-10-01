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
import pickle

# Third-Party
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

    def update_cache(self, key: int = None, value: tuple = None) -> tuple[bool]:
        """Takes in key and value for caching in redis. It sets expiry time for the key.
        And redis, by itself takes care of deleting that key from cache after ttl has been reached.

        Args:
            key: The id of vault in string
            value: The tuples in the vault
        """
        serialized_obj = pickle.dumps(value)
        logger.info(f"Update cache in cache: {key} {serialized_obj}")
        success_set = self.cache.set(key, serialized_obj)
        if success_set:
            logger.debug(f"Cache updated successfully with key: {key} and value {value}")
        else:
            logger.error(f"Cache updated failed for key: {key} and value {value}")
        success_expiry = self.cache.expire(key, self.cache_ttl)
        if success_expiry:
            logger.debug(f"Cache expiry set successfully for key: {key}")
        else:
            logger.error("Failed to set cache expiration")
        return success_set, success_expiry

    def retrieve_cache(self, key: int = None) -> tuple:
        """Retrieves cache for a key value

        Args:
            key: The id of vault in string
            value: The tuples in the vault

        Returns:
            retrieved_obj: Return the retrieved object from cache
        """
        value = self.cache.get(key)
        if value:
            retrieved_obj = pickle.loads(value)
            logger.debug(f"Cache retrieval for id: {key} with value: {retrieved_obj}")
            return retrieved_obj
        else:
            logger.error(f"Cache retrieval unsuccessful for id: {key}")

    def delete_cache(self, key: int = None) -> None:
        """Retrieves cache for a key value

        Args:
            key: The id of vault in string
            value: The tuples in the vault

        Returns:
            retrieved_obj: Return the retrieved object from cache
        """
        logger.info(f"Deleting cache for key : {key}")
        deleted_count = self.cache.delete(key)
        if deleted_count == 1 and self.cache.exists(key) == 0:
            logger.info(f"Cache deleted successfully for key: {key}")
        else:
            logger.info(f"Unsuccessful cache deletion: {key}")
