# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/storage/cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Caching system for MCP Eval Server.
"""

# Standard
from hashlib import sha256
import time
from typing import Any, Dict, Optional

# Third-Party
from cachetools import TTLCache
import diskcache as dc
import orjson


class EvaluationCache:
    """Cache for evaluation results with TTL and persistence options."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600, disk_cache_dir: Optional[str] = None):
        """Initialize cache.

        Args:
            max_size: Maximum number of cached items
            ttl_seconds: Time to live in seconds
            disk_cache_dir: Directory for persistent disk cache
        """
        self.memory_cache = TTLCache(maxsize=max_size, ttl=ttl_seconds)
        self.disk_cache = dc.Cache(disk_cache_dir) if disk_cache_dir else None
        self.ttl_seconds = ttl_seconds

    def _generate_key(self, **kwargs) -> str:
        """Generate cache key from parameters.

        Args:
            **kwargs: Keyword arguments to generate cache key from.

        Returns:
            str: MD5 hash of the sorted parameters as cache key.
        """
        # Sort kwargs for consistent key generation
        sorted_items = sorted(kwargs.items())
        key_bytes = orjson.dumps(sorted_items, option=orjson.OPT_SORT_KEYS)
        return sha256(key_bytes).hexdigest()

    async def get(self, **kwargs) -> Optional[Dict[str, Any]]:
        """Get cached evaluation result.

        Args:
            **kwargs: Parameters that were used to generate the cache key.

        Returns:
            Optional[Dict[str, Any]]: Cached result if found and still valid, None otherwise.
        """
        cache_key = self._generate_key(**kwargs)

        # Check memory cache first
        if cache_key in self.memory_cache:
            return self.memory_cache[cache_key]

        # Check disk cache if available
        if self.disk_cache is not None:
            try:
                if cache_key in self.disk_cache:
                    result = self.disk_cache[cache_key]

                    # Check if still valid
                    if time.time() - result.get("cached_at", 0) < self.ttl_seconds:
                        # Restore to memory cache
                        self.memory_cache[cache_key] = result
                        return result
                    # Expired, remove from disk cache
                    del self.disk_cache[cache_key]
            except Exception:
                # Handle disk cache errors gracefully
                pass

        return None

    async def set(self, result: Dict[str, Any], **kwargs) -> None:
        """Cache evaluation result.

        Args:
            result: The evaluation result to cache.
            **kwargs: Parameters used to generate the cache key.
        """
        cache_key = self._generate_key(**kwargs)

        # Add timestamp
        cached_result = {**result, "cached_at": time.time(), "cache_key": cache_key}

        # Store in memory cache
        self.memory_cache[cache_key] = cached_result

        # Store in disk cache if available
        if self.disk_cache is not None:
            try:
                self.disk_cache[cache_key] = cached_result
            except Exception:
                # Handle disk cache errors gracefully
                pass

    async def invalidate(self, **kwargs) -> None:
        """Invalidate cached result.

        Args:
            **kwargs: Parameters used to identify the cache entry to invalidate.
        """
        cache_key = self._generate_key(**kwargs)

        # Remove from memory cache
        self.memory_cache.pop(cache_key, None)

        # Remove from disk cache
        if self.disk_cache is not None:
            try:
                if cache_key in self.disk_cache:
                    del self.disk_cache[cache_key]
            except Exception:
                # Handle disk cache errors gracefully
                pass

    async def clear(self) -> None:
        """Clear all cached results."""
        self.memory_cache.clear()

        if self.disk_cache is not None:
            try:
                self.disk_cache.clear()
            except Exception:
                # Handle disk cache errors gracefully
                pass

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict[str, Any]: Dictionary containing memory and disk cache statistics.
        """
        memory_stats = {"size": len(self.memory_cache), "max_size": self.memory_cache.maxsize, "hits": getattr(self.memory_cache, "hits", 0), "misses": getattr(self.memory_cache, "misses", 0)}

        disk_stats = {}
        if self.disk_cache:
            disk_stats = {"size": len(self.disk_cache), "volume": self.disk_cache.volume()}

        return {"memory_cache": memory_stats, "disk_cache": disk_stats, "ttl_seconds": self.ttl_seconds}


class JudgeResponseCache(EvaluationCache):
    """Specialized cache for judge responses."""

    async def get_judge_result(self, judge_model: str, response: str, criteria: list, context: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get cached judge evaluation result.

        Args:
            judge_model: The judge model used for evaluation.
            response: The response that was evaluated.
            criteria: List of evaluation criteria.
            context: Optional context for the evaluation.

        Returns:
            Optional[Dict[str, Any]]: Cached judge result if found, None otherwise.
        """
        return await self.get(judge_model=judge_model, response=response, criteria=criteria, context=context)

    async def cache_judge_result(self, result: Dict[str, Any], judge_model: str, response: str, criteria: list, context: Optional[str] = None) -> None:
        """Cache judge evaluation result.

        Args:
            result: The judge evaluation result to cache.
            judge_model: The judge model used for evaluation.
            response: The response that was evaluated.
            criteria: List of evaluation criteria.
            context: Optional context for the evaluation.
        """
        await self.set(result, judge_model=judge_model, response=response, criteria=criteria, context=context)


class BenchmarkCache(EvaluationCache):
    """Specialized cache for benchmark results."""

    async def get_benchmark_result(self, benchmark_suite: str, agent_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached benchmark result.

        Args:
            benchmark_suite: Name of the benchmark suite.
            agent_config: Configuration of the agent that was benchmarked.

        Returns:
            Optional[Dict[str, Any]]: Cached benchmark result if found, None otherwise.
        """
        return await self.get(benchmark_suite=benchmark_suite, agent_config=agent_config)

    async def cache_benchmark_result(self, result: Dict[str, Any], benchmark_suite: str, agent_config: Dict[str, Any]) -> None:
        """Cache benchmark result.

        Args:
            result: The benchmark result to cache.
            benchmark_suite: Name of the benchmark suite.
            agent_config: Configuration of the agent that was benchmarked.
        """
        await self.set(result, benchmark_suite=benchmark_suite, agent_config=agent_config)
