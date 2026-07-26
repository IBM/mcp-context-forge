#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/storage/repository.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

In-memory repository for container scan results.

Stores the most recent ScanResult per image_digest and supports listing
recent scans in reverse-chronological order.  Bounded by max_entries
to keep memory predictable; oldest entries are evicted when full.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Dict, List, Optional

# Local
from plugins.container_scanner.types import ScanResult

logger = logging.getLogger(__name__)


class ScanResultRepository:
    """Bounded in-memory store for container scan results.

    Usage::

        repo = ScanResultRepository(max_entries=500)
        repo.save(scan_result)
        result = repo.get("ghcr.io/org/app:v1")

    Args:
        max_entries: Maximum number of results to retain.
            When the limit is reached, the oldest entry is evicted
            before inserting the new one.
    """
    _max_entries : int
    _store : Dict[str, ScanResult]
    _insertion_order : List[str]

    def __init__(self, max_entries: int = 1000) -> None:
        if max_entries < 1:
            raise ValueError("Maximum number of entries must be a positive number")
        self._max_entries = max_entries
        self._store = {}
        self._insertion_order = []


    def save(self, result: ScanResult) -> None:
        """Persist a scan result, replacing any prior result for the same image.

        If the repository is at capacity and the image_digest is new, the oldest
        entry is evicted to make room.

        Args:
            result: Completed scan result to store.
        """
        key = result.image_digest if result.image_digest else result.image_ref
        if key in self._store:
            # Update existing entry — move to end of order, no eviction needed
            self._insertion_order.remove(key)
        else:
            # New entry — evict oldest if at capacity
            if len(self._store) == self._max_entries:
                oldest = self._insertion_order.pop(0)
                self._store.pop(oldest)
                logger.info("Repository at capacity (%d), evicted oldest entry: %s", self._max_entries, oldest)
        self._store[key] = result
        self._insertion_order.append(key)



    def get(self, image_digest: str) -> Optional[ScanResult]:
        """Return the most recent scan result for *image_digest*, or None.

        Args:
            image_digest: Full image reference (e.g., ``"ghcr.io/org/app:v1"``).

        Returns:
            Stored :class:`ScanResult`, or ``None`` if not found.
        """
        return self._store.get(image_digest)



    def clear(self) -> None:
        """Remove all stored results."""
        self._store.clear()
        self._insertion_order.clear()
        logger.info("ScanResultRepository cleared")

    def list_recent(self) -> List[ScanResult]:
        """Return all stored results, most recent first."""
        return [self._store[key] for key in reversed(self._insertion_order) if key in self._store]

    def __len__(self) -> int:
        """Return the number of stored results."""
        return len(self._store)


# Shared singleton — used by ContainerScannerPlugin and the admin/API routers
container_scan_repo = ScanResultRepository()
