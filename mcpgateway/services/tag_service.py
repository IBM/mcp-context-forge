# -*- coding: utf-8 -*-
"""Tag Service Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This module implements tag management and retrieval for all entities in the MCP Gateway.
It handles:
- Fetching all unique tags across entities
- Filtering tags by entity type
- Tag statistics and counts
- Retrieving entities that have specific tags
"""

# Standard
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


class TagService:
    """Service for managing and retrieving tags across all entities."""

    async def get_all_tags(self, db: Session, entity_types: Optional[List[str]] = None, include_entities: bool = False) -> List[TagInfo]:
        """Retrieve all unique tags across specified entity types.

        Args:
            db: Database session
            entity_types: List of entity types to filter by (tools, resources, prompts, servers, gateways)
                         If None, returns tags from all entity types
            include_entities: Whether to include the list of entities that have each tag

        Returns:
            List of TagInfo objects containing tag details
        """
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
                    for tag in tags:
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
                    for tag in tags:
                        if tag not in tag_data:
                            tag_data[tag] = {"stats": TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=0, total=0), "entities": []}

                        # Update stats
                        self._update_stats(tag_data[tag]["stats"], entity_type)

        # Convert to TagInfo list
        tags = [TagInfo(name=tag, stats=data["stats"], entities=data["entities"] if include_entities else []) for tag, data in sorted(tag_data.items())]

        return tags

    def _update_stats(self, stats: TagStats, entity_type: str) -> None:
        """Update statistics for a specific entity type.

        Args:
            stats: TagStats object to update
            entity_type: Type of entity to increment count for
        """
        if entity_type == "tools":
            stats.tools += 1
        elif entity_type == "resources":
            stats.resources += 1
        elif entity_type == "prompts":
            stats.prompts += 1
        elif entity_type == "servers":
            stats.servers += 1
        elif entity_type == "gateways":
            stats.gateways += 1

        stats.total += 1

    async def get_entities_by_tag(self, db: Session, tag_name: str, entity_types: Optional[List[str]] = None) -> List[TaggedEntity]:
        """Get all entities that have a specific tag.

        Args:
            db: Database session
            tag_name: The tag to search for
            entity_types: Optional list of entity types to filter by

        Returns:
            List of TaggedEntity objects
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
                if tag_name in (entity.tags or []):
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

        Args:
            db: Database session

        Returns:
            Dictionary mapping entity type to count of unique tags
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
