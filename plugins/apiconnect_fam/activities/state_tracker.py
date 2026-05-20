"""Location: ./plugins/apiconnect_fam/activities/state_tracker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Abstract base class for state tracking with content hashing.

This module provides a common foundation for tracking entity state (servers, tools)
using SHA-256 content hashing for change detection.
"""

# Standard
from abc import ABC, abstractmethod
import hashlib
import json
from typing import Any, Dict, Set


class AbstractStateTracker(ABC):
    """Abstract base class for state tracking using content hashing.

    This class provides common functionality for tracking entity state:
    - Content hash computation for change detection
    - Cache management (presence in cache = synced to FAM)
    - New/changed/deleted entity detection

    Subclasses must implement:
    - compute_hash(): Entity-specific hash computation logic

    Attributes:
        _cache: Maps entity_id to content hash (presence = synced to FAM)
    """

    def __init__(self):
        """Initialize state tracker with empty cache."""
        self._cache: Dict[str, str] = {}

    @staticmethod
    @abstractmethod
    def compute_hash(entity: Any) -> str:
        """Compute SHA-256 hash of entity content.

        Subclasses must implement this to define which fields are included
        in the hash computation.

        Args:
            entity: Entity object (Server or Tool ORM object)

        Returns:
            SHA-256 hash string
        """
        pass

    def is_new(self, entity_id: str) -> bool:
        """Check if entity is new (not yet synced to FAM).

        Args:
            entity_id: Entity identifier

        Returns:
            True if entity is new (no hash in cache)
        """
        return entity_id not in self._cache

    def has_changed(self, entity_id: str, current_hash: str) -> bool:
        """Check if entity content has changed since last sync.

        Args:
            entity_id: Entity identifier
            current_hash: Current content hash

        Returns:
            True if entity has changed or is new
        """
        cached_hash = self._cache.get(entity_id)
        return cached_hash != current_hash

    def mark_synced(self, entity_id: str, content_hash: str) -> None:
        """Mark entity as synced to FAM.

        Args:
            entity_id: Entity identifier
            content_hash: Content hash of synced state
        """
        self._cache[entity_id] = content_hash

    def mark_deleted(self, entity_id: str) -> None:
        """Mark entity as deleted from FAM.

        Args:
            entity_id: Entity identifier
        """
        self._cache.pop(entity_id, None)

    def get_deleted_entities(self, current_entity_ids: Set[str]) -> Set[str]:
        """Get entities that were synced to FAM but no longer exist in DB.

        Args:
            current_entity_ids: Set of current entity IDs from database

        Returns:
            Set of entity IDs that were deleted
        """
        synced_entity_ids = set(self._cache.keys())
        return synced_entity_ids - current_entity_ids

    @staticmethod
    def _compute_hash_from_dict(data: Dict[str, Any]) -> str:
        """Helper method to compute SHA-256 hash from dictionary.

        Args:
            data: Dictionary of entity data

        Returns:
            SHA-256 hash string
        """
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()
