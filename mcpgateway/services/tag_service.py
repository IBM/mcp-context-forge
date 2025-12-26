# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tag_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tag Service Implementation.
This module implements tag management and retrieval for all entities in the MCP Gateway.
It handles:
- Fetching all unique tags across entities
- Filtering tags by entity type
- Tag statistics and counts
- Retrieving entities that have specific tags
"""

# Standard
import logging
from typing import Dict, List, Optional

# Third-Party
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import TaggedEntity, TagInfo, TagStats

logger = logging.getLogger(__name__)

# Cache import (lazy to avoid circular dependencies)
_ADMIN_STATS_CACHE = None


def _get_admin_stats_cache():
    """Get admin stats cache singleton lazily.

    Returns:
        AdminStatsCache instance.
    """
    global _ADMIN_STATS_CACHE  # pylint: disable=global-statement
    if _ADMIN_STATS_CACHE is None:
        # First-Party
        from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

        _ADMIN_STATS_CACHE = admin_stats_cache
    return _ADMIN_STATS_CACHE


class TagService:
    """Service for managing and retrieving tags across all entities.

    This service provides comprehensive tag management functionality across all MCP Gateway
    entity types (tools, resources, prompts, servers, gateways). It handles tag discovery,
    entity lookup by tags, and statistics aggregation.

    Example:
        >>> from unittest.mock import MagicMock
        >>> from mcpgateway.schemas import TagInfo, TagStats, TaggedEntity
        >>>
        >>> # Create service instance
        >>> service = TagService()
        >>>
        >>> # Mock database session
        >>> mock_db = MagicMock()
        >>>
        >>> # Test basic functionality
        >>> isinstance(service, TagService)
        True
    """

    async def get_all_tags(self, db: Session, entity_types: Optional[List[str]] = None, include_entities: bool = False) -> List[TagInfo]:
        """Retrieve all unique tags across specified entity types.

        This method aggregates tags from multiple entity types and returns comprehensive
        statistics about tag usage. It can optionally include detailed information about
        which entities have each tag.

        Args:
            db: Database session for querying entity data
            entity_types: List of entity types to filter by. Valid types are:
                         ['tools', 'resources', 'prompts', 'servers', 'gateways'].
                         If None, returns tags from all entity types.
            include_entities: Whether to include the list of entities that have each tag.
                             If False, only statistics are returned for better performance.

        Returns:
            List of TagInfo objects containing tag details, sorted alphabetically by tag name.
            Each TagInfo includes:
            - name: The tag name
            - stats: Usage statistics per entity type
            - entities: List of entities with this tag (if include_entities=True)

        Example:
            >>> import asyncio
            >>> from unittest.mock import MagicMock, AsyncMock
            >>>
            >>> # Create service and mock database
            >>> service = TagService()
            >>> mock_db = MagicMock()
            >>>
            >>> # Mock empty result
            >>> mock_db.execute.return_value.__iter__ = lambda self: iter([])
            >>>
            >>> # Test with empty database
            >>> async def test_empty():
            ...     tags = await service.get_all_tags(mock_db)
            ...     return len(tags)
            >>> asyncio.run(test_empty())
            0

            >>> # Mock result with tag data
            >>> mock_result = MagicMock()
            >>> mock_result.__iter__ = lambda self: iter([
            ...     (["api", "database"],),
            ...     (["api", "web"],),
            ... ])
            >>> mock_db.execute.return_value = mock_result
            >>>
            >>> # Test with tag data
            >>> async def test_with_tags():
            ...     tags = await service.get_all_tags(mock_db, entity_types=["tools"])
            ...     return len(tags) >= 2  # Should have at least api, database, web tags
            >>> asyncio.run(test_with_tags())
            True

            >>> # include_entities=True path
            >>> from types import SimpleNamespace
            >>> entity = SimpleNamespace(id='1', name='E', description='d', tags=['api'])
            >>> mock_result2 = MagicMock()
            >>> mock_result2.scalars.return_value = [entity]
            >>> mock_db.execute.return_value = mock_result2
            >>> async def test_with_entities():
            ...     tags = await service.get_all_tags(mock_db, entity_types=["tools"], include_entities=True)
            ...     return len(tags) == 1 and tags[0].entities[0].name == 'E'
            >>> asyncio.run(test_with_entities())
            True

        Raises:
            SQLAlchemyError: If database query fails
            ValidationError: If invalid entity types are processed
        """
        # Generate cache key from parameters
        entity_types_key = ":".join(sorted(entity_types)) if entity_types else "all"
        cache_key = f"{entity_types_key}:{include_entities}"

        # Check cache first (only for non-entity queries as entity data is large)
        if not include_entities:
            cache = _get_admin_stats_cache()
            cached = await cache.get_tags(cache_key)
            if cached is not None:
                # Reconstruct TagInfo objects from cached dicts
                return [TagInfo.model_validate(t) for t in cached]

        tag_data: Dict[str, Dict] = {}

        # Define entity type mapping
        entity_map = {
            "tools": DbTool,
            "resources": DbResource,
            "prompts": DbPrompt,
            "servers": DbServer,
            "gateways": DbGateway,
        }

        # If no entity types specified, use all
        if entity_types is None:
            entity_types = list(entity_map.keys())

        # Collect tags from each requested entity type
        for entity_type in entity_types:
            if entity_type not in entity_map:
                continue

            model = entity_map[entity_type]

            # Query all entities with tags from this entity type
            if include_entities:
                # Get full entity details
                stmt = select(model).where(model.tags.isnot(None))
                result = db.execute(stmt)

                for entity in result.scalars():
                    tags = entity.tags if entity.tags else []
                    for raw_tag in tags:
                        tag = self._get_tag_id(raw_tag)
                        if tag not in tag_data:
                            tag_data[tag] = {"stats": TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=0, total=0), "entities": []}

                        # Create TaggedEntity
                        # Determine the ID
                        if hasattr(entity, "id") and entity.id is not None:
                            entity_id = str(entity.id)
                        elif entity_type == "resources" and hasattr(entity, "uri"):
                            entity_id = str(entity.uri)
                        else:
                            entity_id = str(entity.name if hasattr(entity, "name") and entity.name else "unknown")

                        # Determine the name
                        if hasattr(entity, "name") and entity.name:
                            entity_name = entity.name
                        elif hasattr(entity, "original_name") and entity.original_name:
                            entity_name = entity.original_name
                        elif hasattr(entity, "uri"):
                            entity_name = str(entity.uri)
                        else:
                            entity_name = entity_id

                        entity_info = TaggedEntity(
                            id=entity_id,
                            name=entity_name,
                            type=entity_type[:-1],  # Remove plural 's'
                            description=entity.description if hasattr(entity, "description") else None,
                        )
                        tag_data[tag]["entities"].append(entity_info)

                        # Update stats
                        self._update_stats(tag_data[tag]["stats"], entity_type)
            else:
                # Just get tags without entity details
                stmt = select(model.tags).where(model.tags.isnot(None))
                result = db.execute(stmt)

                for row in result:
                    tags = row[0] if row[0] else []
                    for raw_tag in tags:
                        tag = self._get_tag_id(raw_tag)
                        if tag not in tag_data:
                            tag_data[tag] = {"stats": TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=0, total=0), "entities": []}

                        # Update stats
                        self._update_stats(tag_data[tag]["stats"], entity_type)

        # Convert to TagInfo list
        tags = [TagInfo(name=tag, stats=data["stats"], entities=data["entities"] if include_entities else []) for tag, data in sorted(tag_data.items())]

        # Store in cache (only for non-entity queries)
        if not include_entities:
            cache = _get_admin_stats_cache()
            await cache.set_tags([t.model_dump() for t in tags], cache_key)

        return tags

    def _update_stats(self, stats: TagStats, entity_type: str) -> None:
        """Update statistics for a specific entity type.

        This helper method increments the appropriate counter in the TagStats object
        based on the entity type and maintains the total count.

        Args:
            stats: TagStats object to update with new counts
            entity_type: Type of entity to increment count for. Must be one of:
                        'tools', 'resources', 'prompts', 'servers', 'gateways'

        Example:
            >>> from mcpgateway.schemas import TagStats
            >>> service = TagService()
            >>> stats = TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=0, total=0)
            >>>
            >>> # Test updating tool stats
            >>> service._update_stats(stats, "tools")
            >>> stats.tools
            1
            >>> stats.total
            1
            >>>
            >>> # Test updating resource stats
            >>> service._update_stats(stats, "resources")
            >>> stats.resources
            1
            >>> stats.total
            2
            >>>
            >>> # Test with invalid entity type (should not crash)
            >>> service._update_stats(stats, "invalid")
            >>> stats.total  # Should remain 2
            2
        """
        if entity_type == "tools":
            stats.tools += 1
            stats.total += 1
        elif entity_type == "resources":
            stats.resources += 1
            stats.total += 1
        elif entity_type == "prompts":
            stats.prompts += 1
            stats.total += 1
        elif entity_type == "servers":
            stats.servers += 1
            stats.total += 1
        elif entity_type == "gateways":
            stats.gateways += 1
            stats.total += 1
        # Invalid entity types are ignored (no increment)

    def _get_tag_id(self, tag) -> str:
        """Return the tag id for a tag entry which may be a string or a dict.

        Supports legacy string tags and new dict tags with an 'id' field.
        Falls back to 'label' or the string representation when 'id' is missing.

        Args:
            tag: Tag value which may be a string (legacy) or a dict with an
                 'id' or 'label' key.

        Returns:
            The normalized tag id as a string.
        """
        if isinstance(tag, str):
            return tag
        if isinstance(tag, dict):
            return tag.get("id") or tag.get("label") or str(tag)
        return str(tag)

    async def get_entities_by_tag(self, db: Session, tag_name: str, entity_types: Optional[List[str]] = None) -> List[TaggedEntity]:
        """Get all entities that have a specific tag.

        This method searches across specified entity types to find all entities
        that contain the given tag. It returns simplified entity representations
        optimized for tag-based discovery and filtering.

        Args:
            db: Database session for querying entity data
            tag_name: The exact tag to search for (case sensitive)
            entity_types: Optional list of entity types to search within.
                         Valid types: ['tools', 'resources', 'prompts', 'servers', 'gateways']
                         If None, searches all entity types

        Returns:
            List of TaggedEntity objects containing basic entity information.
            Each TaggedEntity includes: id, name, type, and description.
            Results are not sorted and may contain entities from different types.

        Example:
            >>> import asyncio
            >>> from unittest.mock import MagicMock
            >>>
            >>> # Setup service and mock database
            >>> service = TagService()
            >>> mock_db = MagicMock()
            >>>
            >>> # Mock entity with tag
            >>> mock_entity = MagicMock()
            >>> mock_entity.id = "test-123"
            >>> mock_entity.name = "Test Entity"
            >>> mock_entity.description = "A test entity"
            >>> mock_entity.tags = ["api", "test", "database"]
            >>>
            >>> # Mock database result
            >>> mock_result = MagicMock()
            >>> mock_result.scalars.return_value = [mock_entity]
            >>> mock_db.execute.return_value = mock_result
            >>>
            >>> # Test entity lookup by tag
            >>> async def test_entity_lookup():
            ...     entities = await service.get_entities_by_tag(mock_db, "api", ["tools"])
            ...     return len(entities)
            >>> asyncio.run(test_entity_lookup())
            1

            >>> # Test with non-existent tag
            >>> mock_entity.tags = ["different", "tags"]
            >>> async def test_no_match():
            ...     entities = await service.get_entities_by_tag(mock_db, "api", ["tools"])
            ...     return len(entities)
            >>> asyncio.run(test_no_match())
            0

        Note:
            - Tag matching is exact and case-sensitive
            - Entities without the specified tag are filtered out after database query
            - Performance scales with the number of entities in filtered types
            - Uses JSON LIKE queries for database-level filtering when possible
        """
        entities = []

        # Define entity type mapping
        entity_map = {
            "tools": DbTool,
            "resources": DbResource,
            "prompts": DbPrompt,
            "servers": DbServer,
            "gateways": DbGateway,
        }

        # If no entity types specified, use all
        if entity_types is None:
            entity_types = list(entity_map.keys())

        for entity_type in entity_types:
            if entity_type not in entity_map:
                continue

            model = entity_map[entity_type]

            # Query entities that have this tag
            # Using JSON contains for PostgreSQL/SQLite JSON columns
            stmt = select(model).where(func.json_extract(model.tags, "$").op("LIKE")(f'%"{tag_name}"%'))
            result = db.execute(stmt)

            for entity in result.scalars():
                entity_tags = entity.tags or []
                entity_tag_ids = [self._get_tag_id(t) for t in entity_tags]
                if tag_name in entity_tag_ids:
                    # Determine the ID
                    if hasattr(entity, "id") and entity.id is not None:
                        entity_id = str(entity.id)
                    elif entity_type == "resources" and hasattr(entity, "uri"):
                        entity_id = str(entity.uri)
                    else:
                        entity_id = str(entity.name if hasattr(entity, "name") and entity.name else "unknown")

                    # Determine the name
                    if hasattr(entity, "name") and entity.name:
                        entity_name = entity.name
                    elif hasattr(entity, "original_name") and entity.original_name:
                        entity_name = entity.original_name
                    elif hasattr(entity, "uri"):
                        entity_name = str(entity.uri)
                    else:
                        entity_name = entity_id

                    entity_info = TaggedEntity(
                        id=entity_id,
                        name=entity_name,
                        type=entity_type[:-1],  # Remove plural 's'
                        description=entity.description if hasattr(entity, "description") else None,
                    )
                    entities.append(entity_info)

        return entities

    async def get_tag_counts(self, db: Session) -> Dict[str, int]:
        """Get count of unique tags per entity type.

        This method calculates the total number of tag instances (not unique tag names)
        across all entity types. Useful for analytics and capacity planning.

        Args:
            db: Database session for querying tag data

        Returns:
            Dictionary mapping entity type names to total tag counts.
            Keys: 'tools', 'resources', 'prompts', 'servers', 'gateways'
            Values: Integer counts of total tag instances in each type

        Example:
            >>> import asyncio
            >>> from unittest.mock import MagicMock
            >>>
            >>> # Setup service and mock database
            >>> service = TagService()
            >>> mock_db = MagicMock()
            >>>
            >>> # Mock tag count results
            >>> mock_db.execute.return_value.scalars.return_value.all.return_value = [2, 1, 3]  # 3 entities with 2, 1, 3 tags each
            >>>
            >>> # Execute method with mocked responses (same values reused for simplicity)
            >>> class _Res:
            ...     def scalars(self):
            ...         class _S:
            ...             def all(self_inner):
            ...                 return [2, 1, 3]
            ...         return _S()
            >>> mock_db.execute.return_value = _Res()
            >>> counts = asyncio.run(service.get_tag_counts(mock_db))
            >>> counts['tools']
            6
            >>> all(isinstance(v, int) for v in counts.values())
            True
            >>> len(counts)
            5

        Note:
            - Counts tag instances, not unique tag names
            - An entity with 3 tags contributes 3 to the count
            - Empty or null tag arrays contribute 0 to the count
            - Uses json_array_length() for efficient counting
        """
        counts = {}

        # Count unique tags for tools
        tool_tags_stmt = select(func.json_array_length(DbTool.tags)).where(DbTool.tags.isnot(None))
        tool_tags = db.execute(tool_tags_stmt).scalars().all()
        counts["tools"] = sum(tool_tags)

        # Count unique tags for resources
        resource_tags_stmt = select(func.json_array_length(DbResource.tags)).where(DbResource.tags.isnot(None))
        resource_tags = db.execute(resource_tags_stmt).scalars().all()
        counts["resources"] = sum(resource_tags)

        # Count unique tags for prompts
        prompt_tags_stmt = select(func.json_array_length(DbPrompt.tags)).where(DbPrompt.tags.isnot(None))
        prompt_tags = db.execute(prompt_tags_stmt).scalars().all()
        counts["prompts"] = sum(prompt_tags)

        # Count unique tags for servers
        server_tags_stmt = select(func.json_array_length(DbServer.tags)).where(DbServer.tags.isnot(None))
        server_tags = db.execute(server_tags_stmt).scalars().all()
        counts["servers"] = sum(server_tags)

        # Count unique tags for gateways
        gateway_tags_stmt = select(func.json_array_length(DbGateway.tags)).where(DbGateway.tags.isnot(None))
        gateway_tags = db.execute(gateway_tags_stmt).scalars().all()
        counts["gateways"] = sum(gateway_tags)

        return counts
