#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/cache/cache_manager.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Cache manager for container scan results. """

# Future
from __future__ import annotations

# Standard
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# Local
from ..types import Vulnerability

logger = logging.getLogger(__name__)


class CacheManager:
    """Manages caching of raw vulnerability lists by image digest.

    Stores only the scanner output (List[Vulnerability]), not policy decisions.
    Policy evaluation is always re-run on a cache hit so that config changes
    (threshold, ignore_cves, fail_on_unfixed) take effect immediately without
    requiring a fresh scan.
    """

    def __init__(self, ttl_hours: int = 24, enabled: bool = True):
        """Initialize cache manager.

        Args:
            ttl_hours: Cache time-to-live in hours (default 24h).
            enabled: Whether caching is enabled (disable for testing).
        """
        self._cache: Dict[str, tuple[List[Vulnerability], datetime]] = {}
        self._ttl_hours = ttl_hours
        self._enabled = enabled
        self._hits = 0
        self._misses = 0

        logger.info(
            "CacheManager initialized",
            extra={
                "ttl_hours": ttl_hours,
                "enabled": enabled,
            },
        )

    def lookup(self, image_digest: Optional[str]) -> Optional[List[Vulnerability]]:
        """Lookup cached vulnerability list by image digest.

        Args:
            image_digest: SHA256 digest of the image (e.g., "sha256:abc123...").

        Returns:
            Cached List[Vulnerability] if valid, None otherwise.
            Policy decisions are NOT cached — callers must re-evaluate.
        """
        # Fast path: return immediately if caching disabled or no digest
        if not self._enabled or not image_digest:
            self._misses += 1
            return None

        # Lookup in cache
        cached_entry = self._cache.get(image_digest)
        if not cached_entry:
            self._misses += 1
            logger.debug("Cache miss", extra={"image_digest": image_digest})
            return None

        # Unpack tuple and validate TTL
        scan_result, cached_at = cached_entry
        entry_age = datetime.now(timezone.utc) - cached_at

        if entry_age > timedelta(hours=self._ttl_hours):
            # Expired - lazy deletion (green computing!)
            del self._cache[image_digest]
            self._misses += 1
            logger.info(
                "Cache expired",
                extra={
                    "image_digest": image_digest,
                    "age_hours": entry_age.total_seconds() / 3600,
                },
            )
            return None

        # Valid cache hit - major compute savings!
        self._hits += 1
        logger.info(
            "Cache HIT - scan avoided",
            extra={
                "image_digest": image_digest,
                "age_hours": entry_age.total_seconds() / 3600,
                "compute_saved": "~2-5 minutes",
            },
        )
        return scan_result

    def store(self, image_digest: Optional[str], vulnerabilities: List[Vulnerability]) -> None:
        """Store raw vulnerability list in cache.

        Args:
            image_digest: SHA256 digest of the image.
            vulnerabilities: Raw scanner output to cache (policy decisions excluded).
        """
        # Skip if caching disabled or no digest
        if not self._enabled or not image_digest:
            return

        self._cache[image_digest] = (vulnerabilities, datetime.now(timezone.utc))
        logger.debug(
            "Cache stored",
            extra={
                "image_digest": image_digest,
                "ttl_hours": self._ttl_hours,
            },
        )

    def invalidate(self, image_digest: str) -> None:
        """Manually invalidate a cached entry.

        Args:
            image_digest: SHA256 digest to invalidate.
        """
        if image_digest in self._cache:
            del self._cache[image_digest]
            logger.debug("Cache invalidated", extra={"image_digest": image_digest})

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        logger.info("Cache cleared")

    def get_stats(self) -> Dict[str, float]:
        """Get cache statistics.

        Returns:
            Dictionary with hits, misses, size, and hit rate.
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0

        return {
            "hits": float(self._hits),
            "misses": float(self._misses),
            "size": float(len(self._cache)),
            "hit_rate_percent": round(hit_rate, 2),
        }
